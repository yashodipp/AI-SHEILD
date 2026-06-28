from __future__ import annotations

from typing import Any
from typing import Optional

from backend.services.live_news_service import fetch_live_news_context


def cross_verify_claim(
    text: str,
    *,
    api_key: str,
    lookback_days: int,
    page_size: int,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> dict[str, Any]:
    live_context = fetch_live_news_context(
        text,
        api_key,
        from_date=from_date,
        to_date=to_date,
        page_size=page_size,
        lookback_days=lookback_days,
    )

    if not live_context.get("enabled"):
        return {
            "available": False,
            "status": "not_configured",
            "score": 0.5,
            "headlines": [],
            "sources": [],
            "reasons": ["Live verification is not configured yet for this environment."],
            "provider": "",
            "raw": live_context,
        }

    if not live_context.get("used"):
        return {
            "available": True,
            "status": "unverified",
            "score": 0.5,
            "headlines": [],
            "sources": [],
            "reasons": [live_context.get("error") or "Live verification could not fetch reliable corroboration right now."],
            "provider": str(live_context.get("provider") or ""),
            "raw": live_context,
        }

    corroboration_score = float(live_context.get("corroboration_score", 0.0) or 0.0)
    fact_check_score = float(live_context.get("fact_check_score", 0.0) or 0.0)
    article_count = int(live_context.get("article_count", 0) or 0)
    supporting_count = int(live_context.get("supporting_article_count", 0) or 0)
    headlines = list(live_context.get("latest_headlines") or [])
    sources = list(live_context.get("supporting_sources") or [])
    provider = str(live_context.get("provider") or "")

    reasons: list[str] = []
    if supporting_count >= 2:
        reasons.append(f"Recent coverage from {len(sources)} source(s) supports the submitted claim.")
    elif article_count == 0:
        reasons.append("No matching recent coverage was found in trusted current-news lookup.")
    else:
        reasons.append("Only limited matching coverage was found for the submitted claim.")

    if fact_check_score > 0:
        reasons.append("Fact-check or debunk-style coverage was detected for related keywords.")

    if fact_check_score >= 0.35:
        status = "contradicted"
        score = max(0.05, 0.45 - fact_check_score * 0.4)
    elif corroboration_score >= 0.5:
        status = "corroborated"
        score = min(0.98, 0.55 + corroboration_score * 0.38)
    elif article_count == 0:
        status = "unverified"
        score = 0.38
    else:
        status = "partial"
        score = 0.5 + corroboration_score * 0.12 - fact_check_score * 0.1

    return {
        "available": True,
        "status": status,
        "score": round(score, 2),
        "headlines": headlines[:3],
        "sources": sources[:5],
        "provider": provider,
        "reasons": reasons,
        "raw": live_context,
    }
