"""Keyword matching and scoring engine."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
import yaml

from crawler.models import MatchDetail, MatchResult


class KeywordRule:
    """Compiled pattern rule with weight and display title."""

    def __init__(
        self,
        pattern: str,
        display: str,
        weight: float,
        case_sensitive: bool = False,
    ):
        self.pattern_str = pattern
        self.display = display
        self.weight = weight
        self.case_sensitive = case_sensitive
        flags = 0 if case_sensitive else re.IGNORECASE
        self.compiled = re.compile(pattern, flags)

    def search(self, text: str) -> re.Match | None:
        return self.compiled.search(text)

    def find_snippet(self, text: str, max_chars: int = 120) -> str:
        """Find the first matching occurrence and extract surrounding context."""
        match = self.compiled.search(text)
        if not match:
            return ""
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        snippet = text[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet


class JobMatcher:
    """Evaluates job postings against configured keyword rules."""

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            # Default to config/keywords.yaml relative to project root
            config_path = Path(__file__).resolve().parent.parent.parent / "config" / "keywords.yaml"
        self.config_path = Path(config_path)
        self.title_rules: list[KeywordRule] = []
        self.tech_rules: list[KeywordRule] = []
        self.hard_reject_patterns: list[re.Pattern] = []
        self.negative_rules: list[KeywordRule] = []
        self.min_score: float = 3.0
        self.remote_patterns: list[re.Pattern] = []
        self.require_tech_or_role_match: bool = True

        self.load_config()

    def load_config(self) -> None:
        """Load and compile patterns from yaml configuration."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Keywords config file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        roles = data.get("roles", {})
        self.title_rules = [
            KeywordRule(
                pattern=r["pattern"],
                display=r.get("display", r["pattern"]),
                weight=float(r.get("weight", 3.0)),
                case_sensitive=r.get("case_sensitive", False),
            )
            for r in roles.get("title_keywords", [])
        ]

        self.tech_rules = [
            KeywordRule(
                pattern=r["pattern"],
                display=r.get("display", r["pattern"]),
                weight=float(r.get("weight", 2.0)),
                case_sensitive=r.get("case_sensitive", False),
            )
            for r in roles.get("tech_keywords", [])
        ]

        exclusions = data.get("exclusions", {})
        self.hard_reject_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in exclusions.get("title_hard_rejects", [])
        ]

        self.negative_rules = [
            KeywordRule(
                pattern=r["pattern"],
                display=r.get("display", r["pattern"]),
                weight=float(r.get("weight", -3.0)),
                case_sensitive=r.get("case_sensitive", False),
            )
            for r in exclusions.get("negative_keywords", [])
        ]

        thresholds = data.get("thresholds", {})
        self.min_score = float(thresholds.get("min_score", 3.0))
        self.require_tech_or_role_match = bool(thresholds.get("require_tech_or_role_match", True))
        self.require_role_title = bool(thresholds.get("require_role_title", True))

        loc_cfg = data.get("location", {})
        self.remote_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in loc_cfg.get("remote_patterns", [])
        ]

    def evaluate(self, title: str, description: str, location: str = "") -> MatchResult:
        """
        Evaluate a job posting.
        Returns MatchResult with score, matches, and rejection status.
        """
        # 1. Check Hard Title Rejections
        for pat in self.hard_reject_patterns:
            if pat.search(title):
                return MatchResult(
                    is_match=False,
                    score=0.0,
                    is_rejected=True,
                    rejection_reason=f"Title matched rejection pattern: '{pat.pattern}'",
                )

        score: float = 0.0
        match_details: list[MatchDetail] = []
        matched_keywords: set[str] = set()

        # 2. Check Title Keywords (high value)
        has_title_role_match = False
        for rule in self.title_rules:
            if rule.search(title):
                score += rule.weight
                has_title_role_match = True
                matched_keywords.add(rule.display)
                match_details.append(
                    MatchDetail(
                        keyword=rule.display,
                        matched_in="title",
                        weight=rule.weight,
                        snippet=rule.find_snippet(title),
                    )
                )

        # 3. Check Tech Keywords
        has_tech_match = False
        full_text = f"{title}\n{description}"
        for rule in self.tech_rules:
            # Check title first (give 1.3x multiplier if tech appears in title)
            if rule.search(title):
                added_weight = round(rule.weight * 1.3, 2)
                score += added_weight
                has_tech_match = True
                matched_keywords.add(rule.display)
                match_details.append(
                    MatchDetail(
                        keyword=f"{rule.display} (in title)",
                        matched_in="title",
                        weight=added_weight,
                        snippet=rule.find_snippet(title),
                    )
                )
            elif rule.search(description):
                score += rule.weight
                has_tech_match = True
                matched_keywords.add(rule.display)
                match_details.append(
                    MatchDetail(
                        keyword=rule.display,
                        matched_in="description",
                        weight=rule.weight,
                        snippet=rule.find_snippet(description),
                    )
                )

        # 4. Check Negative Keywords
        for rule in self.negative_rules:
            if rule.search(full_text):
                score += rule.weight  # weight is negative
                matched_keywords.add(f"NEG:{rule.display}")
                match_details.append(
                    MatchDetail(
                        keyword=f"Negative: {rule.display}",
                        matched_in="text",
                        weight=rule.weight,
                        snippet=rule.find_snippet(full_text),
                    )
                )

        # 5. Remote Check
        is_remote = False
        for pat in self.remote_patterns:
            if pat.search(location) or pat.search(title):
                is_remote = True
                break

        # Check if thresholds are met
        is_match = score >= self.min_score
        has_any_match = has_title_role_match or has_tech_match
        has_title_match = has_title_role_match or any(d.matched_in == "title" for d in match_details)

        if self.require_tech_or_role_match and not has_any_match:
            is_match = False

        if self.require_role_title and not has_title_match:
            is_match = False

        return MatchResult(
            is_match=is_match,
            score=round(score, 2),
            matched_keywords=sorted(list(matched_keywords)),
            match_details=match_details,
            is_rejected=False,
            is_remote=is_remote,
        )
