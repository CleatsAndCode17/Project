"""Safe website fetcher: multi-page same-domain crawler, SSRF redirect validator, and HTML cleaner."""

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from app.security import validate_url

DEFAULT_USER_AGENT = "CompanyResearcherBot/1.0 (+http://localhost; ResearchAgent)"
MAX_DOWNLOAD_BYTES = 1024 * 1024  # 1 MB
MAX_PAGE_CHARS = 10000
MAX_TOTAL_CHARS = 30000
MAX_REDIRECTS = 3

PRIORITY_KEYWORDS = [
    "about",
    "product",
    "products",
    "services",
    "solutions",
    "customers",
    "pricing",
]

UNWANTED_TAGS = [
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "svg",
    "noscript",
    "aside",
    "iframe",
    "object",
    "embed",
    "form",
    "button",
]


@dataclass
class FetchResult:
    success: bool
    url: str
    combined_text: str = ""
    pages_crawled: int = 0
    is_js_sparse: bool = False
    error: Optional[str] = None


def extract_visible_text(html_content: str, max_chars: int = MAX_PAGE_CHARS) -> Tuple[str, bool]:
    """
    Parse HTML, decompose non-content tags, collapse whitespace, and return visible text.
    Also detects signs of JavaScript-only single page applications.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Check for noscript JavaScript warnings before stripping
    noscript_tags = soup.find_all("noscript")
    has_js_warning = any(
        re.search(r"enable javascript|javascript is required|turn on javascript", tag.get_text(), re.IGNORECASE)
        for tag in noscript_tags
    )

    # Decompose unwanted elements
    for tag_name in UNWANTED_TAGS:
        for element in soup.find_all(tag_name):
            element.decompose()

    # Extract text and collapse multiple whitespaces
    raw_text = soup.get_text(separator=" ")
    collapsed_text = re.sub(r"[ \t\r\f\v]+", " ", raw_text)
    collapsed_text = re.sub(r"\n\s*\n+", "\n\n", collapsed_text).strip()

    is_sparse = len(collapsed_text) < 100 or has_js_warning

    if len(collapsed_text) > max_chars:
        collapsed_text = collapsed_text[:max_chars]

    return collapsed_text, is_sparse


def extract_priority_links(base_url: str, html_content: str, max_links: int) -> List[str]:
    """
    Extract same-domain links from HTML that match priority company keywords.
    """
    try:
        base_parsed = urlparse(base_url)
        base_netloc = base_parsed.netloc.lower()
    except Exception:
        return []

    soup = BeautifulSoup(html_content, "html.parser")
    scored_links: List[Tuple[int, str]] = []
    seen_urls: Set[str] = {base_url.rstrip("/")}

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        try:
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
        except Exception:
            continue

        # Strictly same domain only
        if parsed.netloc.lower() != base_netloc:
            continue

        # Strip fragment and normalize
        clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if not clean_url or clean_url in seen_urls:
            continue

        # Score matching keywords in path or link text
        link_text = a_tag.get_text().lower()
        path_lower = parsed.path.lower()

        score = 0
        for kw in PRIORITY_KEYWORDS:
            if kw in path_lower:
                score += 3
            if kw in link_text:
                score += 2

        if score > 0:
            seen_urls.add(clean_url)
            scored_links.append((score, clean_url))

    # Sort descending by score
    scored_links.sort(key=lambda x: x[0], reverse=True)
    return [url for _, url in scored_links[:max_links]]


class SafeFetcher:
    """HTTP fetcher with SSRF validation on initial request and every redirect."""

    def __init__(self, timeout: float = 10.0, user_agent: str = DEFAULT_USER_AGENT):
        self.timeout = timeout
        self.user_agent = user_agent

    async def fetch_single_page(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Fetch a single page following at most MAX_REDIRECTS, validating each hop for SSRF.
        Returns: (html_content, error_message)
        """
        current_url = url
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            verify=True,
        ) as client:
            for hop in range(MAX_REDIRECTS + 1):
                # SSRF validation before every request / redirect
                is_valid, err_or_host, norm_url = validate_url(current_url)
                if not is_valid:
                    return None, f"Security block on URL: {err_or_host}"

                try:
                    # Stream response to enforce 1 MB max size limit
                    async with client.stream("GET", norm_url, headers=headers) as response:
                        # Handle redirects manually to validate destination
                        if response.is_redirect:
                            if hop >= MAX_REDIRECTS:
                                return None, "Too many redirects."
                            location = response.headers.get("location")
                            if not location:
                                return None, "Redirect missing location header."
                            current_url = urljoin(str(response.url), location)
                            continue

                        # Check HTTP status
                        if response.status_code >= 400:
                            return None, f"HTTP error {response.status_code}"

                        # Check content type if provided
                        content_type = response.headers.get("content-type", "").lower()
                        if content_type and not any(ct in content_type for ct in ("text/", "html", "xml", "json")):
                            return None, f"Unsupported content-type: {content_type}"

                        # Read at most MAX_DOWNLOAD_BYTES
                        chunks = []
                        total_bytes = 0
                        async for chunk in response.aiter_bytes():
                            total_bytes += len(chunk)
                            if total_bytes > MAX_DOWNLOAD_BYTES:
                                chunks.append(chunk[: MAX_DOWNLOAD_BYTES - (total_bytes - len(chunk))])
                                break
                            chunks.append(chunk)

                        body = b"".join(chunks)
                        # Decode HTML (try utf-8, fallback to latin-1)
                        try:
                            text = body.decode("utf-8")
                        except UnicodeDecodeError:
                            text = body.decode("latin-1", errors="replace")

                        return text, None

                except httpx.TimeoutException:
                    return None, "Request timed out."
                except httpx.RequestError as exc:
                    return None, f"Connection error: {exc}"
                except Exception as exc:
                    return None, f"Fetch error: {exc}"

            return None, "Exceeded maximum redirects."

    async def crawl_site(self, start_url: str, max_pages: int = 4) -> FetchResult:
        """
        Crawl start_url (homepage) and up to max_pages total pages on the same domain.
        """
        # 1. Fetch homepage
        homepage_html, err = await self.fetch_single_page(start_url)
        if err or not homepage_html:
            return FetchResult(
                success=False,
                url=start_url,
                error="I couldn't open this website.",
            )

        home_text, is_js_sparse = extract_visible_text(homepage_html, max_chars=MAX_PAGE_CHARS)
        pages_crawled = 1
        page_texts = [f"--- Page 1: Homepage ({start_url}) ---\n{home_text}"]
        total_chars = len(home_text)

        # 2. Extract priority extra pages
        extra_page_budget = max(0, max_pages - 1)
        if extra_page_budget > 0 and not is_js_sparse:
            extra_urls = extract_priority_links(start_url, homepage_html, max_links=extra_page_budget)
            for i, page_url in enumerate(extra_urls, start=2):
                if total_chars >= MAX_TOTAL_CHARS:
                    break

                page_html, page_err = await self.fetch_single_page(page_url)
                if page_err or not page_html:
                    # Skip secondary page failures gracefully
                    continue

                sub_text, _ = extract_visible_text(page_html, max_chars=MAX_PAGE_CHARS)
                if not sub_text:
                    continue

                page_texts.append(f"\n--- Page {i}: {page_url} ---\n{sub_text}")
                total_chars += len(sub_text)
                pages_crawled += 1

        combined = "\n\n".join(page_texts)
        if len(combined) > MAX_TOTAL_CHARS:
            combined = combined[:MAX_TOTAL_CHARS]

        return FetchResult(
            success=True,
            url=start_url,
            combined_text=combined,
            pages_crawled=pages_crawled,
            is_js_sparse=is_js_sparse,
        )
