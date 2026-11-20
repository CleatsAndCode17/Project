"""Tests for security module: URL extraction, normalization, SSRF protection, and rate limiting."""

import pytest
from app.security import (
    RateLimiter,
    clean_url_candidate,
    extract_urls,
    format_untrusted_data_envelope,
    validate_url,
)


def test_clean_url_candidate():
    assert clean_url_candidate("stripe.com.") == "stripe.com"
    assert clean_url_candidate("daraz.pk,") == "daraz.pk"
    assert clean_url_candidate("https://example.com/test! ") == "https://example.com/test"
    assert clean_url_candidate("(https://stripe.com)") == "https://stripe.com"


def test_url_extraction_and_normalization():
    # 1. Bare domain
    first, has_multiple, all_urls = extract_urls("Check out stripe.com for payments.")
    assert first == "https://stripe.com"
    assert not has_multiple
    assert all_urls == ["https://stripe.com"]

    # 2. Fully qualified URL
    first, has_multiple, all_urls = extract_urls("Visit https://systemsltd.com/services today.")
    assert first == "https://systemsltd.com/services"
    assert not has_multiple
    assert all_urls == ["https://systemsltd.com/services"]

    # 3. Multiple URLs / domains
    first, has_multiple, all_urls = extract_urls("Compare stripe.com with daraz.pk and https://systemsltd.com")
    assert first == "https://stripe.com"
    assert has_multiple is True
    assert len(all_urls) == 3
    assert "https://daraz.pk" in all_urls
    assert "https://systemsltd.com" in all_urls

    # 4. No URL
    first, has_multiple, all_urls = extract_urls("Hello, how are you today?")
    assert first is None
    assert has_multiple is False
    assert all_urls == []


@pytest.mark.parametrize(
    "invalid_scheme_url",
    [
        "ftp://example.com",
        "file:///etc/passwd",
        "gopher://evil.com",
        "javascript:alert(1)",
        "data:text/html,test",
    ],
)
def test_ssrf_blocking_invalid_schemes(invalid_scheme_url):
    is_valid, msg, norm = validate_url(invalid_scheme_url)
    assert is_valid is False
    assert "scheme" in msg.lower() or "unsupported" in msg.lower()


@pytest.mark.parametrize(
    "internal_ip_url",
    [
        "http://localhost",
        "https://127.0.0.1",
        "http://127.0.1.1/admin",
        "http://10.0.0.1",
        "http://10.255.255.255",
        "http://192.168.1.1",
        "http://172.16.0.1",
        "http://172.31.255.255",
        "http://169.254.169.254/latest/meta-data/",  # Cloud metadata
        "http://169.254.1.1",
        "http://0.0.0.0",
        "http://[::1]",
        "http://[fe80::1]",
        "http://[fc00::1]",
    ],
)
def test_ssrf_blocking_private_and_metadata_ips(internal_ip_url):
    is_valid, msg, norm = validate_url(internal_ip_url)
    assert is_valid is False
    assert any(term in msg.lower() for term in ("blocked", "security", "host"))


def test_rate_limiter():
    limiter = RateLimiter(limit_per_minute=3)
    client_ip = "198.51.100.42"

    # First 3 requests must succeed
    assert limiter.is_allowed(client_ip) is True
    assert limiter.is_allowed(client_ip) is True
    assert limiter.is_allowed(client_ip) is True

    # 4th request must be blocked
    assert limiter.is_allowed(client_ip) is False

    # Other IP should still be allowed
    other_ip = "198.51.100.43"
    assert limiter.is_allowed(other_ip) is True

    # After reset, original IP should be allowed
    limiter.reset(client_ip)
    assert limiter.is_allowed(client_ip) is True


def test_format_untrusted_data_envelope():
    envelope = format_untrusted_data_envelope("https://example.com", "Sample company text")
    assert "=== BEGIN UNTRUSTED WEBSITE DATA ===" in envelope
    assert "=== END UNTRUSTED WEBSITE DATA ===" in envelope
    assert "SOURCE URL: https://example.com" in envelope
    assert "Sample company text" in envelope
