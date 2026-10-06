"""Unit tests for job normalizer."""

from crawler.normalizer import (
    canonicalize_url,
    clean_html_text,
    generate_job_id,
    is_remote_location,
    normalize_fuzzy_key,
)


def test_canonicalize_url_strips_tracking():
    raw_url = "https://job-boards.greenhouse.io/gitlab/jobs/123/?utm_source=linkedin&gh_src=camp1&ref=xyz"
    clean = canonicalize_url(raw_url)
    assert "utm_source" not in clean
    assert "gh_src" not in clean
    assert "ref" not in clean
    assert clean == "https://job-boards.greenhouse.io/gitlab/jobs/123"


def test_clean_html_text():
    html_input = "<p>Join our team!<br/>We need a <strong>Go</strong> developer.</p><ul><li>Docker</li><li>K8s</li></ul>"
    text = clean_html_text(html_input)
    assert "<p>" not in text
    assert "<strong>" not in text
    assert "Go developer" in text
    assert "Docker" in text


def test_generate_job_id_deterministic():
    id1 = generate_job_id("greenhouse:gitlab", "1001", "https://example.com/job")
    id2 = generate_job_id("greenhouse:gitlab", "1001", "https://example.com/job")
    id3 = generate_job_id("greenhouse:gitlab", "1002", "https://example.com/job")
    assert id1 == id2
    assert len(id1) == 16
    assert id1 != id3


def test_normalize_fuzzy_key():
    key1 = normalize_fuzzy_key("GitLab Inc.", "Backend Engineer (Remote)", "Remote")
    key2 = normalize_fuzzy_key("GitLab", "Backend Engineer", "Remote, Worldwide")
    assert key1 == key2
    assert key1 == "gitlab|backend engineer|remote"


def test_is_remote_location():
    assert is_remote_location("Remote, US", "Software Engineer")
    assert is_remote_location("Worldwide", "Backend Developer (WFH)")
    assert not is_remote_location("New York, NY", "Office Manager")
