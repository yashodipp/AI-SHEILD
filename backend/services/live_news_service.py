from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from xml.etree import ElementTree

import requests

from backend.utils.scoring import clamp
from backend.utils.text_processing import extract_words


NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"
GOOGLE_NEWS_RSS_ENDPOINT = "https://news.google.com/rss/search"
NEWS_STOPWORDS = {
    "a",
    "about",
    "all",
    "and",
    "are",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "new",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "with",
    "का",
    "के",
    "की",
    "को",
    "पर",
    "में",
    "यह",
    "और",
    "एक",
    "लिए",
    "से",
    "है",
    "हैं",
    "था",
    "थी",
}
FACT_CHECK_MARKERS = (
    "fact check",
    "false",
    "fake",
    "hoax",
    "misleading",
    "not true",
    "debunk",
    "फैक्ट चेक",
    "झूठा",
    "फर्जी",
)


def build_empty_context(*, enabled: bool, query: str = "", provider: str = "", error: str = "") -> dict[str, Any]:
    return {
        "enabled": enabled,
        "used": False,
        "provider": provider,
        "query": query,
        "article_count": 0,
        "supporting_article_count": 0,
        "supporting_sources": [],
        "corroboration_score": 0.0,
        "fact_check_score": 0.0,
        "latest_headlines": [],
        "error": error,
    }


def build_news_query(text: str) -> str:
    tokens = []
    for word in extract_words(text):
        lowered = word.lower()
        if len(lowered) < 3 or lowered in NEWS_STOPWORDS:
            continue
        if lowered not in tokens:
            tokens.append(lowered)
        if len(tokens) >= 8:
            break
    return " ".join(tokens) if tokens else text.strip()[:140]


def article_match_score(claim_tokens: set[str], title: str, description: str) -> tuple[float, int]:
    article_tokens = {word.lower() for word in extract_words(f"{title} {description}")}
    overlap = claim_tokens & article_tokens
    if not claim_tokens:
        return 0.0, 0
    return len(overlap) / len(claim_tokens), len(overlap)


def clean_text(value: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(no_tags).split())


def normalize_articles(
    articles: list[dict[str, Any]],
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    from_boundary = None
    to_boundary = None

    if from_date:
        try:
            from_boundary = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        except ValueError:
            from_boundary = None
    if to_date:
        try:
            to_boundary = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            to_boundary = None

    for article in articles:
        published_at = str(article.get("publishedAt") or "")
        if published_at:
            try:
                published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            except ValueError:
                published_dt = None
            if published_dt is not None:
                if from_boundary and published_dt < from_boundary:
                    continue
                if to_boundary and published_dt >= to_boundary:
                    continue
        filtered.append(article)

    return filtered


def score_live_articles(text: str, articles: list[dict[str, Any]], query: str) -> dict[str, Any]:
    claim_tokens = {
        word.lower()
        for word in extract_words(text)
        if len(word) >= 3 and word.lower() not in NEWS_STOPWORDS
    }

    strong_matches: list[dict[str, Any]] = []
    fact_checks: list[dict[str, Any]] = []
    supporting_sources: set[str] = set()

    for article in articles:
        title = str(article.get("title") or "")
        description = str(article.get("description") or "")
        score, overlap_count = article_match_score(claim_tokens, title, description)
        article_text = f"{title} {description}".lower()
        if score >= 0.28 or overlap_count >= 3:
            strong_matches.append(article)
            source_name = str((article.get("source") or {}).get("name") or "").strip()
            if source_name:
                supporting_sources.add(source_name)
        if any(marker in article_text for marker in FACT_CHECK_MARKERS):
            fact_checks.append(article)

    corroboration_score = clamp(len(strong_matches) * 0.18 + len(supporting_sources) * 0.1, 0.0, 1.0)
    fact_check_score = clamp(len(fact_checks) * 0.22, 0.0, 1.0)

    latest_headlines = []
    headline_source = strong_matches[:3] or articles[:3]
    for article in headline_source:
        latest_headlines.append(
            {
                "title": article.get("title"),
                "source": (article.get("source") or {}).get("name"),
                "published_at": article.get("publishedAt"),
            }
        )

    return {
        "enabled": True,
        "used": True,
        "query": query,
        "article_count": len(articles),
        "supporting_article_count": len(strong_matches),
        "supporting_sources": sorted(supporting_sources),
        "corroboration_score": round(corroboration_score, 2),
        "fact_check_score": round(fact_check_score, 2),
        "latest_headlines": latest_headlines,
    }


def fetch_newsapi_articles(
    query: str,
    api_key: str,
    *,
    from_value: str,
    to_value: str,
    page_size: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    params = {
        "q": query,
        "sortBy": "publishedAt",
        "pageSize": max(1, min(page_size, 10)),
        "from": from_value,
        "to": to_value,
        "apiKey": api_key,
    }
    response = requests.get(NEWSAPI_ENDPOINT, params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    return payload.get("articles") or []


def parse_google_news_articles(xml_payload: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_payload)
    parsed_articles: list[dict[str, Any]] = []

    for item in root.findall("./channel/item"):
        title_text = clean_text(item.findtext("title", default=""))
        link_text = clean_text(item.findtext("link", default=""))
        description_text = clean_text(item.findtext("description", default=""))
        published_raw = clean_text(item.findtext("pubDate", default=""))

        source_name = ""
        if " - " in title_text:
            headline, source_name = title_text.rsplit(" - ", 1)
        else:
            headline = title_text

        published_at = ""
        if published_raw:
            try:
                published_at = parsedate_to_datetime(published_raw).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError, OverflowError):
                published_at = ""

        parsed_articles.append(
            {
                "title": headline,
                "description": description_text,
                "publishedAt": published_at,
                "url": link_text,
                "source": {"name": source_name or "Google News"},
            }
        )

    return parsed_articles


def fetch_google_news_articles(
    query: str,
    *,
    lookback_days: int,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    response = requests.get(
        GOOGLE_NEWS_RSS_ENDPOINT,
        params={
            "q": f"{query} when:{max(1, lookback_days)}d",
            "hl": "en-IN",
            "gl": "IN",
            "ceid": "IN:en",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return parse_google_news_articles(response.text)


def fetch_live_news_context(
    text: str,
    api_key: str,
    *,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page_size: int = 8,
    lookback_days: int = 7,
    timeout_seconds: float = 6.0,
) -> dict[str, Any]:
    if not text.strip():
        return build_empty_context(enabled=False)

    query = build_news_query(text)
    now = datetime.now(timezone.utc)
    from_value = from_date or (now - timedelta(days=lookback_days)).date().isoformat()
    to_value = to_date or now.date().isoformat()
    last_error = ""

    if api_key:
        try:
            articles = fetch_newsapi_articles(
                query,
                api_key,
                from_value=from_value,
                to_value=to_value,
                page_size=page_size,
                timeout_seconds=timeout_seconds,
            )
            scored = score_live_articles(text, normalize_articles(articles, from_date=from_value, to_date=to_value), query)
            scored["provider"] = "newsapi"
            return scored
        except Exception as error:
            last_error = str(error)

    try:
        articles = fetch_google_news_articles(query, lookback_days=lookback_days, timeout_seconds=timeout_seconds)
        scored = score_live_articles(text, normalize_articles(articles, from_date=from_value, to_date=to_value), query)
        scored["provider"] = "google_news_rss"
        return scored
    except Exception as error:
        error_message = str(error)
        if last_error:
            error_message = f"{last_error}; fallback failed: {error_message}"
        return build_empty_context(enabled=True, query=query, provider="newsapi" if api_key else "google_news_rss", error=error_message)
