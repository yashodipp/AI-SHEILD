from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import urlparse

import requests


LOGGER = logging.getLogger(__name__)

TITLE_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL),
)
DESCRIPTION_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL),
    re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL),
)
SCRIPT_LIKE_PATTERN = re.compile(r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
ARTICLE_PATTERN = re.compile(r"<article[^>]*>(.*?)</article>", re.IGNORECASE | re.DOTALL)
PARAGRAPH_PATTERN = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
MIN_ARTICLE_BODY_WORDS = 24


def _clean_fragment(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(without_tags).split())


def _first_match(patterns: tuple[re.Pattern[str], ...], html_text: str) -> str:
    for pattern in patterns:
        match = pattern.search(html_text)
        if match:
            cleaned = _clean_fragment(match.group(1))
            if cleaned:
                return cleaned
    return ""


def _strip_noise(html_text: str) -> str:
    return re.sub(SCRIPT_LIKE_PATTERN, " ", html_text or "")


def _extract_body_text(html_text: str, description: str) -> tuple[str, int, str]:
    cleaned_html = _strip_noise(html_text)
    article_blocks = ARTICLE_PATTERN.findall(cleaned_html)
    candidate_blocks = article_blocks if article_blocks else [cleaned_html]

    paragraphs: list[str] = []
    for block in candidate_blocks:
        paragraphs.extend(_clean_fragment(item) for item in PARAGRAPH_PATTERN.findall(block))

    paragraphs = [item for item in paragraphs if len(item.split()) >= 6]
    body = " ".join(paragraphs[:14]).strip()
    extraction_method = "paragraphs"
    if not body and description:
        body = description
        extraction_method = "description-fallback"

    body_word_count = len(body.split())
    return body[:8000], body_word_count, extraction_method


def extract_article_from_url(url: str, timeout_seconds: float = 6.0) -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, timeout=timeout_seconds, headers=headers, allow_redirects=True)
        response.raise_for_status()
    except Exception as error:
        return {
            "success": False,
            "url": url,
            "resolved_url": url,
            "domain": (urlparse(url).netloc or "").lower(),
            "title": "",
            "description": "",
            "body": "",
            "error": str(error),
        }

    content_type = (response.headers.get("content-type") or "").lower()
    if content_type and "html" not in content_type and "text" not in content_type and "xml" not in content_type:
        LOGGER.info("article_extract_rejected_non_html url=%s content_type=%s", url, content_type)
        return {
            "success": False,
            "url": url,
            "resolved_url": str(response.url),
            "domain": (urlparse(str(response.url)).netloc or "").lower(),
            "title": "",
            "description": "",
            "body": "",
            "status_code": response.status_code,
            "content_type": content_type,
            "error": "The URL did not return an HTML article page.",
        }

    html_text = response.text
    title = _first_match(TITLE_PATTERNS, html_text)
    description = _first_match(DESCRIPTION_PATTERNS, html_text)
    body, body_word_count, extraction_method = _extract_body_text(html_text, description)

    resolved_url = response.url
    domain = (urlparse(resolved_url).netloc or "").lower()
    if domain.startswith("www."):
        domain = domain[4:]

    extraction_success = body_word_count >= MIN_ARTICLE_BODY_WORDS or (body_word_count >= 14 and len(title.split()) >= 4)
    if not extraction_success:
        LOGGER.info(
            "article_extract_insufficient_text url=%s resolved_url=%s title_words=%s body_words=%s method=%s",
            url,
            resolved_url,
            len(title.split()),
            body_word_count,
            extraction_method,
        )
        return {
            "success": False,
            "url": url,
            "resolved_url": resolved_url,
            "domain": domain,
            "title": title,
            "description": description,
            "body": body,
            "status_code": response.status_code,
            "content_type": content_type,
            "body_word_count": body_word_count,
            "extraction_method": extraction_method,
            "error": "AI Shield could not extract enough article text from this URL.",
        }

    LOGGER.info(
        "article_extract_success url=%s resolved_url=%s body_words=%s method=%s",
        url,
        resolved_url,
        body_word_count,
        extraction_method,
    )

    return {
        "success": extraction_success,
        "url": url,
        "resolved_url": resolved_url,
        "domain": domain,
        "title": title,
        "description": description,
        "body": body,
        "status_code": response.status_code,
        "content_type": content_type,
        "body_word_count": body_word_count,
        "extraction_method": extraction_method,
    }
