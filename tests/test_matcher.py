"""Unit tests for keyword matching and scoring engine."""

from crawler.matcher import JobMatcher


def test_matcher_word_boundaries_go_vs_google():
    matcher = JobMatcher()

    # "Google" alone should NOT trigger "Go"
    res_google = matcher.evaluate(
        title="Google Operations Manager",
        description="Support enterprise clients with Google products and algorithms.",
    )
    assert not any("Go" == k or "Golang" == k for k in res_google.matched_keywords)

    # "Go" or "Golang" should match
    res_go = matcher.evaluate(
        title="Go Developer",
        description="Write concurrent services in Go and gRPC.",
    )
    assert res_go.is_match
    assert "Go Engineer" in res_go.matched_keywords or "Go" in res_go.matched_keywords


def test_matcher_title_higher_weight_than_description():
    matcher = JobMatcher()

    # Tech in title gets bonus multiplier
    res_title_tech = matcher.evaluate(
        title="Python Engineer",
        description="General software tasks.",
    )

    res_desc_tech = matcher.evaluate(
        title="Software Engineer",
        description="General tasks with Python.",
    )

    assert res_title_tech.score > res_desc_tech.score


def test_matcher_hard_rejection():
    matcher = JobMatcher()

    res = matcher.evaluate(
        title="Vice President of Engineering",
        description="Lead backend engineering team.",
    )
    assert not res.is_match
    assert res.is_rejected
    assert "rejection pattern" in res.rejection_reason


def test_matcher_negative_keyword_penalty():
    matcher = JobMatcher()

    res_normal = matcher.evaluate(
        title="Backend Engineer",
        description="Experience in Go and PostgreSQL.",
    )

    res_penalized = matcher.evaluate(
        title="Backend Engineer",
        description="Experience in Go and PostgreSQL. Requires 10+ years of enterprise experience.",
    )

    assert res_penalized.score < res_normal.score
    assert any("NEG:" in k for k in res_penalized.matched_keywords)


def test_matcher_fullstack_and_backend():
    matcher = JobMatcher()

    res_fs = matcher.evaluate(
        title="Full Stack Engineer",
        description="We build products using TypeScript, React, and Python.",
        location="Remote",
    )
    assert res_fs.is_match
    assert res_fs.is_remote
    assert "Full Stack Engineer" in res_fs.matched_keywords
    assert "Python" in res_fs.matched_keywords
