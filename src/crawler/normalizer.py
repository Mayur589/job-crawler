"""Normalization and cleaning utilities for job posts."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from bs4 import BeautifulSoup

TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gh_src",
    "ref",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "source",
}

COMPANY_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|technologies|tech|gmbh)\.?\b",
    re.IGNORECASE,
)

TITLE_TAGS = re.compile(
    r"\s*(\([^\)]*remote[^\)]*\)|\[[^\]]*remote[^\]]*\]|\(m/f/d\)|\(m/w/d\)|\(all genders\))\s*",
    re.IGNORECASE,
)


def canonicalize_url(url: str) -> str:
    """Strip marketing and tracking query parameters from job URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        filtered_queries = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_QUERY_PARAMS
        ]
        # Rebuild query string in sorted order for consistent URLs
        sorted_query = urlencode(sorted(filtered_queries))
        # Strip trailing slash from path for consistency
        path = parsed.path.rstrip("/")
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.params,
            sorted_query,
            "",  # Strip fragment
        ))
    except Exception:
        return url.strip()


def clean_html_text(html_or_text: str) -> str:
    """Clean HTML tags and normalize whitespace into clean readable text."""
    if not html_or_text:
        return ""
    import html
    # First unescape HTML entities (e.g. &lt;div&gt; -> <div>)
    raw = html.unescape(html_or_text)
    if "<" in raw and ">" in raw:
        soup = BeautifulSoup(raw, "html.parser")
        # Replace line breaking tags with newlines
        for br in soup.find_all(["br", "p", "div", "li", "tr"]):
            br.append(" ")
        text = soup.get_text()
    else:
        text = raw

    # Normalize multiple whitespace and newlines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def generate_job_id(source: str, source_job_id: str, canonical_url: str = "") -> str:
    """Generate a deterministic 16-character hex hash ID for the job."""
    if source and source_job_id:
        key = f"{source.lower().strip()}:{str(source_job_id).strip()}"
    else:
        key = canonical_url.strip()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def normalize_fuzzy_key(company: str, title: str, location: str = "") -> str:
    """
    Generate a normalized key for cross-source fuzzy deduplication.
    e.g. "GitLab Inc." + "Backend Engineer (Remote)" -> "gitlab|backend engineer|remote"
    """
    # Clean company
    c = COMPANY_SUFFIXES.sub("", company.lower())
    c = re.sub(r"[^a-z0-9]", "", c)

    # Clean title
    t = TITLE_TAGS.sub("", title.lower())
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    # Clean location (remote or country/city)
    loc = location.lower()
    is_remote = bool(re.search(r"\b(remote|anywhere|distributed|wfh)\b", loc))
    if is_remote:
        loc_token = "remote"
    else:
        loc_token = re.sub(r"[^a-z0-9]", "", loc)

    return f"{c}|{t}|{loc_token}"


def is_remote_location(location: str, title: str, description: str = "") -> bool:
    """Detect if the role is remote from location or title."""
    pattern = re.compile(r"\b(remote|anywhere|work\s+from\s+home|wfh|distributed)\b", re.IGNORECASE)
    return bool(pattern.search(location) or pattern.search(title))
