from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Optional
from urllib.parse import urlparse
from uuid import uuid4

from backend.database.log_analysis import store_analysis_log
from backend.database.mongo_store import store_mongo_analysis
from backend.database.report_db import store_report_metadata
from backend.models.fake_news_model import analyze_news
from backend.services.article_extractor_service import extract_article_from_url
from backend.services.fact_verification_service import cross_verify_claim
from backend.services.image_verification_service import analyze_image_file
from backend.services.report_service import create_report_bundle
from backend.services.source_credibility_service import analyze_source_credibility
from backend.utils.scoring import calibrated_confidence, clamp
from backend.utils.text_processing import extract_text_signals

try:
    from transformers import pipeline
except Exception:  # pragma: no cover - optional dependency
    pipeline = None


LOGGER = logging.getLogger(__name__)
TRANSFORMER_PIPELINE = None
TRANSFORMER_LOAD_ATTEMPTED = False
FAST_NEWS_TIMEOUT_SECONDS = 2.5


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("AI Shield requires a valid http or https news URL.")


def _fast_news_mode_enabled() -> bool:
    return os.getenv("AI_SHIELD_FAST_MODE", "true").lower() != "false"


def _language_key(language: Optional[str], text: str) -> str:
    if language == "hi":
        return "hi"
    if language == "en":
        return "en"
    return "hi" if any("\u0900" <= character <= "\u097F" for character in text) else "en"


def _load_transformer_pipeline() -> Optional[Any]:
    global TRANSFORMER_PIPELINE
    global TRANSFORMER_LOAD_ATTEMPTED

    if TRANSFORMER_LOAD_ATTEMPTED:
        return TRANSFORMER_PIPELINE

    TRANSFORMER_LOAD_ATTEMPTED = True
    if pipeline is None or os.getenv("AI_SHIELD_ENABLE_TRANSFORMER", "false").lower() != "true":
        return None

    model_name = os.getenv("AI_SHIELD_TRANSFORMER_MODEL", "distilroberta-base")
    local_only = os.getenv("AI_SHIELD_TRANSFORMER_LOCAL_ONLY", "true").lower() == "true"

    try:
        TRANSFORMER_PIPELINE = pipeline(
            "text-classification",
            model=model_name,
            tokenizer=model_name,
            truncation=True,
            max_length=512,
            top_k=None,
            local_files_only=local_only,
        )
    except Exception:
        TRANSFORMER_PIPELINE = None
    return TRANSFORMER_PIPELINE


def _transformer_prediction(headline: str, body: str, language: str) -> dict[str, Any]:
    classifier = _load_transformer_pipeline()
    combined_text = f"{headline}\n\n{body}".strip()
    if classifier is None or not combined_text:
        return {
            "available": False,
            "used": False,
            "provider": "",
            "model": "",
            "fake_probability": None,
            "confidence": None,
        }

    try:
        predictions = classifier(combined_text)
        if predictions and isinstance(predictions[0], list):
            predictions = predictions[0]
        label_scores = {
            str(item.get("label", "")).lower(): float(item.get("score", 0.0))
            for item in (predictions or [])
        }
        fake_probability = None

        for label, score in label_scores.items():
            if any(token in label for token in ("fake", "misleading", "false", "label_0")):
                fake_probability = score
                break

        if fake_probability is None:
            positive_score = max(label_scores.values()) if label_scores else 0.5
            fake_probability = 1 - positive_score

        fake_probability = round(clamp(fake_probability, 0.02, 0.98), 2)
        confidence = round(max(label_scores.values()) if label_scores else 0.5, 2)
        return {
            "available": True,
            "used": True,
            "provider": "huggingface-transformers",
            "model": os.getenv("AI_SHIELD_TRANSFORMER_MODEL", "distilroberta-base"),
            "fake_probability": fake_probability,
            "confidence": confidence,
        }
    except Exception:
        return {
            "available": True,
            "used": False,
            "provider": "huggingface-transformers",
            "model": os.getenv("AI_SHIELD_TRANSFORMER_MODEL", "distilroberta-base"),
            "fake_probability": None,
            "confidence": None,
        }


@lru_cache(maxsize=64)
def _cached_source_result(url: str) -> tuple[tuple[str, Any], ...]:
    result = analyze_source_credibility(url)
    return tuple(result.items())


@lru_cache(maxsize=64)
def _cached_fact_result(query_text: str, api_key: str, lookback_days: int, page_size: int) -> tuple[tuple[str, Any], ...]:
    result = cross_verify_claim(
        query_text,
        api_key=api_key,
        lookback_days=lookback_days,
        page_size=page_size,
    )
    return tuple(result.items())


@lru_cache(maxsize=32)
def _cached_article_result(url: str, timeout_seconds: float) -> tuple[tuple[str, Any], ...]:
    article = extract_article_from_url(url, timeout_seconds=timeout_seconds)
    return tuple(article.items())


def _runtime_timeout(timeout_seconds: float) -> float:
    if not _fast_news_mode_enabled():
        return float(timeout_seconds)
    return min(float(timeout_seconds), FAST_NEWS_TIMEOUT_SECONDS)


def _maybe_cached_fact_result(query_text: str, api_key: str, lookback_days: int, page_size: int) -> dict[str, Any]:
    if not query_text.strip() or not api_key:
        return cross_verify_claim(
            query_text,
            api_key=api_key,
            lookback_days=lookback_days,
            page_size=page_size,
        )
    return dict(_cached_fact_result(query_text, api_key, lookback_days, page_size))


def _style_scores(headline: str, body: str) -> dict[str, float]:
    headline_signals = extract_text_signals(headline)
    body_signals = extract_text_signals(body)

    clickbait_score = clamp(
        len(headline_signals["suspicious_terms"]) * 0.09
        + len(headline_signals["suspicious_phrases"]) * 0.16
        + headline_signals["exclamation_count"] * 0.05,
        0.0,
        1.0,
    )
    emotional_tone_score = clamp(
        headline_signals["uppercase_ratio"] * 0.75
        + body_signals["uppercase_ratio"] * 0.25
        + headline_signals["question_count"] * 0.03
        + body_signals["exclamation_count"] * 0.02,
        0.0,
        1.0,
    )
    misleading_language_score = clamp(
        len(body_signals["manipulation_phrases"]) * 0.1
        + len(body_signals["negated_credibility"]) * 0.12
        + body_signals["source_gap"] * 0.18,
        0.0,
        1.0,
    )
    return {
        "clickbait_score": round(clickbait_score, 2),
        "emotional_tone_score": round(emotional_tone_score, 2),
        "misleading_language_score": round(misleading_language_score, 2),
    }


def _build_text_payload(headline: str, body: str) -> dict[str, str]:
    clean_headline = " ".join(headline.strip().split())
    clean_body = " ".join(body.strip().split())
    if clean_headline and clean_body:
        combined = f"{clean_headline}. {clean_body}"
    else:
        combined = clean_headline or clean_body
    return {
        "headline": clean_headline,
        "body": clean_body,
        "combined": combined,
    }


def _finalize_prediction(
    *,
    analysis_type: str,
    input_name: str,
    text_result: dict[str, Any],
    source_result: Optional[dict[str, Any]] = None,
    fact_result: Optional[dict[str, Any]] = None,
    image_result: Optional[dict[str, Any]] = None,
    transformer_result: Optional[dict[str, Any]] = None,
    article: Optional[dict[str, Any]] = None,
    style_scores: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    baseline_fake = float(text_result["fake_probability"])
    source_risk = 1 - float((source_result or {}).get("score", 0.55))
    fact_status = str((fact_result or {}).get("status", "unverified"))
    image_fake = float((image_result or {}).get("fake_probability", 0.45))
    style_scores = style_scores or {}

    if fact_status == "corroborated":
        fact_risk = 0.12
    elif fact_status == "contradicted":
        fact_risk = 0.82
    elif fact_status == "partial":
        fact_risk = 0.42
    else:
        fact_risk = 0.55

    style_risk = (
        float(style_scores.get("clickbait_score", 0.0)) * 0.45
        + float(style_scores.get("emotional_tone_score", 0.0)) * 0.2
        + float(style_scores.get("misleading_language_score", 0.0)) * 0.35
    )

    transformer_fake = transformer_result.get("fake_probability") if transformer_result else None

    weighted_sum = baseline_fake * 0.54 + style_risk * 0.16
    total_weight = 0.7

    if transformer_fake is not None:
        weighted_sum += float(transformer_fake) * 0.16
        total_weight += 0.16
    if source_result:
        weighted_sum += source_risk * 0.1
        total_weight += 0.1
    if fact_result:
        weighted_sum += fact_risk * 0.2
        total_weight += 0.2
    if image_result:
        weighted_sum += image_fake * 0.08
        total_weight += 0.08

    fake_probability = round(clamp(weighted_sum / total_weight, 0.02, 0.98), 2)
    if style_scores.get("clickbait_score", 0) >= 0.35 and fact_status in {"unverified", "contradicted"}:
        fake_probability = round(clamp(fake_probability + 0.06, 0.02, 0.98), 2)
    if style_scores.get("misleading_language_score", 0) >= 0.3 and fact_status != "corroborated":
        fake_probability = round(clamp(fake_probability + 0.05, 0.02, 0.98), 2)
    real_probability = round(1 - fake_probability, 2)
    transformer_confidence = float((transformer_result or {}).get("confidence") or 0.0)
    status = "Fake" if fake_probability >= 0.5 else "Real"
    clickbait_score = float(style_scores.get("clickbait_score", 0.0))
    misleading_score = float(style_scores.get("misleading_language_score", 0.0))
    emotional_score = float(style_scores.get("emotional_tone_score", 0.0))
    if status == "Fake":
        support_score = min(
            1.0,
            (0.32 if fact_status == "contradicted" else 0.0)
            + clickbait_score * 0.2
            + misleading_score * 0.24
            + emotional_score * 0.08
            + baseline_fake * 0.14
            + (0.12 if fake_probability >= 0.7 else 0.0)
            + (0.1 if (source_result or {}).get("trust_level") == "low" else 0.0)
            + (0.08 if fact_status == "unverified" and fake_probability >= 0.7 else 0.0)
            + transformer_confidence * 0.08,
        )
        contradiction_score = min(
            1.0,
            (0.36 if fact_status == "corroborated" else 0.0)
            + (0.12 if (source_result or {}).get("trust_level") == "high" else 0.0)
            + (0.08 if clickbait_score < 0.2 and misleading_score < 0.2 else 0.0),
        )
    else:
        support_score = min(
            1.0,
            (0.34 if fact_status == "corroborated" else 0.0)
            + (0.12 if (source_result or {}).get("trust_level") == "high" else 0.0)
            + (0.18 if baseline_fake <= 0.18 or fake_probability <= 0.18 else 0.0)
            + (0.1 if clickbait_score < 0.2 and misleading_score < 0.2 else 0.0)
            + (
                0.08
                if fact_status == "unverified"
                and baseline_fake <= 0.22
                and clickbait_score < 0.2
                and misleading_score < 0.2
                else 0.0
            )
            + (0.05 if fake_probability <= 0.16 else 0.0)
            + transformer_confidence * 0.08,
        )
        contradiction_score = min(
            1.0,
            (0.36 if fact_status == "contradicted" else 0.0)
            + clickbait_score * 0.18
            + misleading_score * 0.22
            + (0.1 if (source_result or {}).get("trust_level") == "low" else 0.0),
        )
    confidence = calibrated_confidence(
        fake_probability,
        0.5,
        support_score,
        contradiction_score,
        floor=0.58,
        ceiling=0.99,
        base=0.6 + transformer_confidence * 0.05,
        precision=2,
    )

    explanation = []
    if style_scores.get("clickbait_score", 0) >= 0.35:
        explanation.append("Clickbait-style headline patterns were detected.")
    if style_scores.get("misleading_language_score", 0) >= 0.25:
        explanation.append("Misleading or low-evidence language was detected in the submitted content.")
    if source_result and source_result.get("trust_level") == "low":
        explanation.append("The linked source has a low credibility score.")
    if fact_result and fact_result.get("status") == "contradicted":
        explanation.append("Current cross-verification found contradictory or debunk-style coverage.")
    elif fact_result and fact_result.get("status") == "unverified":
        explanation.append("No strong verification was found in recent trusted coverage.")
    elif fact_result and fact_result.get("status") == "corroborated":
        explanation.append("Recent trusted coverage supports the submitted claim.")
    if image_result and image_result["fake_probability"] >= 0.58:
        explanation.append("Image metadata suggests reuse, heavy redistribution, or editing traces.")

    explanation.extend(text_result.get("explanation", [])[:2])
    if analysis_type == "news_url" and article.get("success") is False:
        explanation.insert(0, "The article text could not be fully extracted from this URL, so AI Shield used source-level and fallback text signals.")
    explanation = explanation[:6] or ["The final prediction combines model output, source trust, and cross-verification signals."]

    summary = (
        f"AI Shield classified this news input as {status.lower()} with "
        f"{int(fake_probability * 100)}% fake probability and {int(confidence * 100)}% confidence."
    )

    article = article or {}
    return {
        "analysis_type": analysis_type,
        "input_name": input_name,
        "status": status,
        "prediction": status.upper(),
        "fake_probability": fake_probability,
        "real_probability": real_probability,
        "confidence": confidence,
        "summary": summary,
        "explanation": explanation,
        "article": article,
        "style_analysis": style_scores,
        "model": {
            "mode": "transformer-hybrid" if transformer_fake is not None else "hybrid-heuristic",
            "baseline_fake_probability": baseline_fake,
            "transformer_used": int(transformer_fake is not None),
            "transformer_model": (transformer_result or {}).get("model", ""),
            "transformer_fake_probability": transformer_fake,
        },
        "source_credibility": source_result,
        "fact_verification": fact_result,
        "image_verification": image_result,
        "metadata": {
            **text_result.get("metadata", {}),
            "article_domain": article.get("domain", ""),
            "source_score": float((source_result or {}).get("score", 0.0) or 0.0),
            "fact_status": fact_status,
            "fact_score": float((fact_result or {}).get("score", 0.0) or 0.0),
            "clickbait_score": float(style_scores.get("clickbait_score", 0.0)),
            "emotional_tone_score": float(style_scores.get("emotional_tone_score", 0.0)),
            "misleading_language_score": float(style_scores.get("misleading_language_score", 0.0)),
            "article_extraction_success": 0 if analysis_type == "news_url" and article.get("success") is False else 1,
            "style_signals_available": 0 if analysis_type == "news_url" and article.get("success") is False else 1,
            "transformer_used": int(transformer_fake is not None),
            "transformer_model": (transformer_result or {}).get("model", ""),
            "fast_mode": int(_fast_news_mode_enabled()),
        },
    }


def analyze_news_text_input(
    headline: str,
    body: str,
    *,
    language: Optional[str] = None,
    live_api_key: str = "",
    lookback_days: int = 7,
    page_size: int = 8,
) -> dict[str, Any]:
    text_payload = _build_text_payload(headline, body)
    selected_language = _language_key(language, text_payload["combined"])
    baseline_result = analyze_news(text_payload["combined"])
    transformer_result = _transformer_prediction(text_payload["headline"], text_payload["body"], selected_language)
    style_scores = _style_scores(text_payload["headline"], text_payload["body"])
    fact_result = _maybe_cached_fact_result(
        text_payload["combined"],
        api_key=live_api_key,
        lookback_days=lookback_days,
        page_size=page_size,
    )
    return _finalize_prediction(
        analysis_type="news_text",
        input_name=text_payload["headline"][:60] or "submitted_news_text",
        text_result=baseline_result,
        fact_result=fact_result,
        transformer_result=transformer_result,
        style_scores=style_scores,
        article={
            "headline": text_payload["headline"],
            "body": text_payload["body"][:1500],
            "language": selected_language,
        },
    )


def analyze_news_url_input(
    url: str,
    *,
    language: Optional[str] = None,
    live_api_key: str = "",
    lookback_days: int = 7,
    page_size: int = 8,
    timeout_seconds: float = 6.0,
) -> dict[str, Any]:
    normalized_url = url.strip()
    _validate_http_url(normalized_url)
    runtime_timeout = _runtime_timeout(timeout_seconds)
    LOGGER.info("news_url_analysis_start url=%s timeout=%s", normalized_url, runtime_timeout)
    article = dict(_cached_article_result(normalized_url, runtime_timeout))
    source_result = dict(_cached_source_result(normalized_url))
    LOGGER.info(
        "news_url_extract url=%s success=%s body_words=%s method=%s",
        normalized_url,
        int(bool(article.get("success"))),
        article.get("body_word_count", 0),
        article.get("extraction_method", ""),
    )

    article_text = f"{article.get('title', '')}. {article.get('body', '')}".strip()
    if not article.get("success"):
        source_score = float(source_result.get("score") or 0.5)
        risky_match = bool(source_result.get("risky_match"))
        high_risk_source = risky_match or source_score <= 0.28
        if high_risk_source:
            fake_probability = round(clamp(0.62 + max(0.0, 0.4 - source_score) * 0.4, 0.56, 0.82), 2)
            status = "Fake"
            confidence = 0.56
        else:
            fake_probability = round(clamp(0.46 + (0.5 - source_score) * 0.14, 0.34, 0.58), 2)
            status = "Real"
            confidence = 0.54

        explanation = [
            "The article text could not be extracted from this URL, so AI Shield used a conservative source-only news fallback.",
            *source_result.get("reasons", [])[:2],
        ]
        return {
            "analysis_type": "news_url",
            "input_name": source_result.get("domain", url),
            "status": status,
            "prediction": status.upper(),
            "fake_probability": fake_probability,
            "real_probability": round(1 - fake_probability, 2),
            "confidence": confidence,
            "summary": (
                f"AI Shield classified this news URL as {status.lower()} with "
                f"{int(fake_probability * 100)}% fake probability using source-level signals only."
            ),
            "explanation": explanation,
            "article": article,
            "style_analysis": {"clickbait_score": 0.0, "emotional_tone_score": 0.0, "misleading_language_score": 0.0},
            "model": {
                "mode": "source-fallback-hybrid",
                "baseline_fake_probability": fake_probability,
                "transformer_used": 0,
                "transformer_model": "",
                "transformer_fake_probability": None,
            },
            "source_credibility": source_result,
            "fact_verification": {
                "status": "unavailable",
                "score": 0.0,
                "reasons": ["Full article extraction was unavailable for this URL, so cross-verification stayed limited."],
                "headlines": [],
            },
            "image_verification": None,
            "metadata": {
                "article_domain": article.get("domain", ""),
                "source_score": source_score,
                "fact_status": "unavailable",
                "fact_score": 0.0,
                "clickbait_score": 0.0,
                "emotional_tone_score": 0.0,
                "misleading_language_score": 0.0,
                "article_extraction_success": 0,
                "style_signals_available": 0,
                "source_only_assessment": 1,
                "transformer_used": 0,
                "transformer_model": "",
                "fast_mode": int(_fast_news_mode_enabled()),
                "url_debug": {
                    "input_url": normalized_url,
                    "resolved_url": article.get("resolved_url", normalized_url),
                    "content_type": article.get("content_type", ""),
                    "article_extraction_success": 0,
                    "article_body_word_count": article.get("body_word_count", 0),
                    "article_extraction_method": article.get("extraction_method", ""),
                    "model_input_text_words": 0,
                },
            },
        }

    result = analyze_news_text_input(
        article.get("title", ""),
        article.get("body", ""),
        language=language,
        live_api_key=live_api_key,
        lookback_days=lookback_days,
        page_size=page_size,
    )
    result["analysis_type"] = "news_url"
    result["input_name"] = source_result.get("domain", url)
    result["article"] = {
        **article,
        "language": result.get("article", {}).get("language", article.get("language", "")),
    }
    result["source_credibility"] = source_result
    result.setdefault("metadata", {})
    result["metadata"].update(
        {
            "article_domain": article.get("domain", ""),
            "source_score": float(source_result.get("score", 0.0) or 0.0),
            "article_extraction_success": 1,
            "style_signals_available": 1,
            "source_only_assessment": 0,
            "source_url": normalized_url,
            "url_debug": {
                "input_url": normalized_url,
                "resolved_url": article.get("resolved_url", normalized_url),
                "content_type": article.get("content_type", ""),
                "article_extraction_success": 1,
                "article_body_word_count": article.get("body_word_count", 0),
                "article_extraction_method": article.get("extraction_method", ""),
                "model_input_text_words": len(article_text.split()),
                "model_input_title_words": len(str(article.get("title", "")).split()),
            },
        }
    )
    LOGGER.info(
        "news_url_prediction url=%s prediction=%s fake_probability=%s confidence=%s text_words=%s",
        normalized_url,
        result.get("prediction"),
        result.get("fake_probability"),
        result.get("confidence"),
        len(article_text.split()),
    )
    result["metadata"]["url_conservative_override"] = 0
    return result


def analyze_news_image_input(
    image_path: str,
    filename: str,
    *,
    caption: str = "",
    live_api_key: str = "",
    lookback_days: int = 7,
    page_size: int = 8,
) -> dict[str, Any]:
    image_result = analyze_image_file(image_path, filename, caption)
    text_result = analyze_news(caption or filename)
    fact_result = _maybe_cached_fact_result(
        caption or filename,
        api_key=live_api_key,
        lookback_days=lookback_days,
        page_size=page_size,
    )
    style_scores = _style_scores(caption or filename, caption)
    return _finalize_prediction(
        analysis_type="news_image",
        input_name=filename,
        text_result=text_result,
        fact_result=fact_result,
        image_result=image_result,
        article={"headline": caption, "body": "", "language": _language_key(None, caption)},
        style_scores=style_scores,
    )


def persist_news_analysis(
    result: dict[str, Any],
    *,
    database_path: str,
    reports_dir: str,
    mongo_uri: str = "",
    mongo_database: str = "ai_shield",
) -> dict[str, Any]:
    analysis_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()

    result["analysis_id"] = analysis_id
    result["created_at"] = created_at

    record = {
        "id": analysis_id,
        "analysis_type": result["analysis_type"],
        "input_name": result["input_name"],
        "status": result["status"],
        "fake_probability": result["fake_probability"],
        "real_probability": result["real_probability"],
        "confidence": result["confidence"],
        "summary": result["summary"],
        "metadata": result["metadata"],
        "created_at": created_at,
    }

    store_analysis_log(database_path, record)
    store_mongo_analysis(
        mongo_uri,
        mongo_database,
        {
            **record,
            "prediction": result["prediction"],
            "article": result.get("article"),
            "source_credibility": result.get("source_credibility"),
            "fact_verification": result.get("fact_verification"),
            "image_verification": result.get("image_verification"),
            "style_analysis": result.get("style_analysis"),
            "model": result.get("model"),
        },
    )

    report = create_report_bundle(result, reports_dir)
    report["analysis_id"] = analysis_id
    store_report_metadata(database_path, report)

    return {
        "analysis_id": analysis_id,
        "created_at": created_at,
        "report": {
            "id": report["id"],
            "pdf_url": f"/api/reports/{report['id']}?format=pdf",
            "csv_url": f"/api/reports/{report['id']}?format=csv",
        },
    }
