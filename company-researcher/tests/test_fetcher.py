"""Tests for website fetcher: HTML cleaning, visible text extraction, and link filtering."""

import pytest
from app.fetcher import (
    extract_priority_links,
    extract_visible_text,
    SafeFetcher,
    FetchResult,
)


def test_extract_visible_text_strips_unwanted_tags():
    html = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>Test Company</title>
        <style>body { color: red; }</style>
        <script>alert('malicious');</script>
      </head>
      <body>
        <header>Header content to drop</header>
        <nav><a href="/home">Home</a><a href="/faq">FAQ</a></nav>
        <main>
          <h1>Leading AI Solutions for Modern Global Enterprises</h1>
          <p>We provide enterprise automation software that transforms business operations at scale.</p>
          <svg><path d="M0 0"/></svg>
        </main>
        <footer>Copyright 2026 Company Inc.</footer>
      </body>
    </html>
    """
    text, is_sparse = extract_visible_text(html)

    # Content from allowed tags should be present
    assert "Leading AI Solutions" in text
    assert "We provide enterprise automation software" in text

    # Disallowed tags must be decomposed
    assert "body { color: red; }" not in text
    assert "alert('malicious')" not in text
    assert "Header content to drop" not in text
    assert "Copyright 2026 Company Inc." not in text
    assert not is_sparse


def test_extract_visible_text_whitespace_collapse():
    html = """
    <div>
        Hello      world!
        
        This   is    spaced    out.
    </div>
    """
    text, _ = extract_visible_text(html)
    assert "Hello world!" in text
    assert "This is spaced out." in text
    assert "      " not in text


def test_extract_visible_text_truncation():
    long_content = "<p>" + "A" * 15000 + "</p>"
    text, _ = extract_visible_text(long_content, max_chars=500)
    assert len(text) == 500


def test_extract_visible_text_js_sparse_detection():
    sparse_html = "<html><body><noscript>You need to enable JavaScript to run this app.</noscript><div id='root'></div></body></html>"
    text, is_sparse = extract_visible_text(sparse_html)
    assert is_sparse is True


def test_extract_priority_links():
    base_url = "https://example.com"
    html = """
    <html>
      <body>
        <a href="/about-us">About Us</a>
        <a href="/products/cloud">Cloud Products</a>
        <a href="/pricing">Pricing Plans</a>
        <a href="/careers">Careers</a>
        <a href="https://external-partner.com/about">External Partner</a>
        <a href="mailto:info@example.com">Email Us</a>
        <a href="#section">Anchor</a>
      </body>
    </html>
    """
    links = extract_priority_links(base_url, html, max_links=3)

    assert len(links) <= 3
    # Same-domain priority links should be present
    assert "https://example.com/about-us" in links or "https://example.com/products/cloud" in links or "https://example.com/pricing" in links
    # External and non-http links must be absent
    assert not any("external-partner.com" in link for link in links)
    assert not any("mailto" in link for link in links)


@pytest.mark.asyncio
async def test_safe_fetcher_crawl_failure(monkeypatch):
    fetcher = SafeFetcher(timeout=1.0)

    # Simulate network failure on homepage
    async def mock_fetch_single_page(url):
        return None, "Connection refused"

    monkeypatch.setattr(fetcher, "fetch_single_page", mock_fetch_single_page)

    res = await fetcher.crawl_site("https://example.com")
    assert res.success is False
    assert res.error == "I couldn't open this website."
