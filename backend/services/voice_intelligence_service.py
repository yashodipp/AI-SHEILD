from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4

import requests
from requests import exceptions as request_exceptions

from backend.models.fake_voice_model import analyze_audio
from backend.services.source_credibility_service import analyze_source_credibility
from backend.utils.scoring import clamp
from backend.utils.file_handler import ensure_runtime_dirs


LOGGER = logging.getLogger(__name__)
AUDIO_EXTENSIONS = {".wav", ".mp3", ".aac", ".m4a", ".ogg"}
AUDIO_URL_HINTS = ("audio", "voice", "speech", ".wav", ".mp3", ".aac", ".m4a", ".ogg")
HTML_AUDIO_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:audio(?::url)?["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<audio[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<source[^>]+src=["\']([^"\']+\.(?:wav|mp3|aac|m4a|ogg)[^"\']*)["\']', re.IGNORECASE),
)
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
MAX_AUDIO_DOWNLOAD_BYTES = 40 * 1024 * 1024
MIN_AUDIO_DOWNLOAD_BYTES = 2 * 1024
FAST_VOICE_TIMEOUT_SECONDS = 2.5
STREAMING_PLATFORM_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "m.youtube.com",
    "facebook.com",
    "fb.watch",
    "instagram.com",
    "x.com",
    "twitter.com",
)
HTML_PAYLOAD_MARKERS = (b"<!doctype html", b"<html", b"<head", b"<body", b"<script")


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("AI Shield requires a valid http or https audio URL.")
STRONG_SYNTHETIC_SOURCE_TERMS = (
    "aivoicegenerator",
    "voicemaker",
    "elevenlabs",
    "playht",
    "murf",
    "resemble",
    "wellsaid",
    "speechify",
)


def _guess_filename(url: str, response: Optional[requests.Response] = None) -> str:
    if response is not None:
        disposition = response.headers.get("content-disposition", "")
        match = re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE)
        if match:
            return match.group(1)

    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name or "audio.wav"
    return name if Path(name).suffix.lower() in AUDIO_EXTENSIONS else f"{name}.wav"


def _looks_like_direct_audio(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in AUDIO_URL_HINTS) or Path(urlparse(url).path).suffix.lower() in AUDIO_EXTENSIONS


def _voice_fast_mode_enabled() -> bool:
    return os.getenv("AI_SHIELD_FAST_MODE", "true").lower() != "false"


def _runtime_timeout(timeout_seconds: float) -> float:
    if not _voice_fast_mode_enabled():
        return float(timeout_seconds)
    return min(float(timeout_seconds), FAST_VOICE_TIMEOUT_SECONDS)


def _is_streaming_platform(url: str) -> bool:
    domain = (urlparse(url).netloc or "").lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == item or domain.endswith(f".{item}") for item in STREAMING_PLATFORM_DOMAINS)


def _friendly_voice_url_error(url: str, error: Exception) -> str:
    if _is_streaming_platform(url):
        return (
            "This link is from a streaming platform like YouTube. "
            "AI Shield voice URL mode cannot reliably extract audio directly from that page in this lightweight runtime. "
            "Use a direct audio link or upload the audio file."
        )
    if isinstance(error, request_exceptions.Timeout):
        return "The source took too long to respond. Try again, use a direct audio link, or upload the audio file."
    if isinstance(error, request_exceptions.ConnectionError):
        return "AI Shield could not connect to this audio source right now. Try again or upload the audio file."
    return "AI Shield could not fetch a playable audio stream from this URL right now."


def _looks_like_html_payload(sample: bytes) -> bool:
    lowered = sample.lstrip().lower()
    return any(marker in lowered[:512] for marker in HTML_PAYLOAD_MARKERS)


def _looks_like_audio_payload(sample: bytes) -> bool:
    prefix = sample[:128]
    return (
        prefix.startswith(b"RIFF")
        or prefix.startswith(b"ID3")
        or prefix.startswith(b"OggS")
        or prefix.startswith(b"fLaC")
        or prefix.startswith(b"\xff\xf1")
        or prefix.startswith(b"\xff\xf9")
        or b"ftyp" in prefix
    )


def _discover_audio_asset(url: str, timeout_seconds: float) -> dict[str, Any]:
    if _is_streaming_platform(url):
        return {
            "download_url": None,
            "mode": "unresolved",
            "discovery_notes": [
                "This URL belongs to a streaming platform like YouTube, so direct audio extraction is not available in lightweight URL mode."
            ],
        }

    response = requests.get(url, timeout=(2.5, timeout_seconds), headers=REQUEST_HEADERS, allow_redirects=True)
    response.raise_for_status()

    content_type = (response.headers.get("content-type") or "").lower()
    final_url = str(response.url)
    if content_type.startswith("audio/") or _looks_like_direct_audio(final_url):
        return {
            "download_url": final_url,
            "mode": "direct",
            "discovery_notes": ["The submitted URL points directly to an audio resource."],
        }

    html = response.text[:300_000]
    for pattern in HTML_AUDIO_PATTERNS:
        match = pattern.search(html)
        if match:
            return {
                "download_url": urljoin(final_url, match.group(1).strip()),
                "mode": "embedded",
                "discovery_notes": ["A playable audio URL was discovered from page metadata."],
            }

    return {
        "download_url": None,
        "mode": "unresolved",
        "discovery_notes": ["No downloadable audio stream was exposed by the submitted page."],
    }


@lru_cache(maxsize=32)
def _cached_discovery(url: str, timeout_seconds: float) -> tuple[tuple[str, Any], ...]:
    result = _discover_audio_asset(url, timeout_seconds)
    return tuple(result.items())


def _download_audio(url: str, uploads_dir: str, timeout_seconds: float) -> dict[str, Any]:
    bucket = Path(uploads_dir) / "audio-url"
    ensure_runtime_dirs(str(bucket))

    response = requests.get(url, timeout=(2.5, timeout_seconds), headers=REQUEST_HEADERS, allow_redirects=True, stream=True)
    response.raise_for_status()

    original_name = _guess_filename(url, response)
    stored_path = bucket / f"{uuid4().hex}_{original_name}"

    downloaded_bytes = 0
    truncated = False
    head_sample = bytearray()
    with stored_path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            if len(head_sample) < 4096:
                remaining = 4096 - len(head_sample)
                head_sample.extend(chunk[:remaining])
            next_size = downloaded_bytes + len(chunk)
            if next_size > MAX_AUDIO_DOWNLOAD_BYTES:
                allowed_bytes = MAX_AUDIO_DOWNLOAD_BYTES - downloaded_bytes
                if allowed_bytes > 0:
                    handle.write(chunk[:allowed_bytes])
                    downloaded_bytes += allowed_bytes
                truncated = True
                break
            handle.write(chunk)
            downloaded_bytes = next_size

    content_type = (response.headers.get("content-type") or "").lower()
    html_like = _looks_like_html_payload(bytes(head_sample))
    media_like = _looks_like_audio_payload(bytes(head_sample))
    content_valid = True
    validation_reason = ""
    if downloaded_bytes < MIN_AUDIO_DOWNLOAD_BYTES:
        content_valid = False
        validation_reason = "The resolved URL returned too little data to validate a playable audio clip."
    elif html_like:
        content_valid = False
        validation_reason = "The resolved URL returned an HTML page instead of an audio file."
    elif not content_type.startswith("audio/") and not media_like:
        content_valid = False
        validation_reason = "The resolved URL did not return a recognizable audio payload."

    return {
        "path": str(stored_path),
        "original_name": original_name,
        "downloaded_bytes": downloaded_bytes,
        "truncated": truncated,
        "content_type": content_type,
        "content_valid": int(content_valid),
        "validation_reason": validation_reason,
        "head_signature": bytes(head_sample[:64]).decode("latin1", errors="ignore"),
    }


def _neutral_audio_name(original_name: str) -> str:
    suffix = Path(original_name).suffix.lower() or ".wav"
    if suffix not in AUDIO_EXTENSIONS:
        suffix = ".wav"
    return f"url_audio_sample{suffix}"


def _has_strong_synthetic_name(original_name: str) -> bool:
    lowered = original_name.lower()
    return any(term in lowered for term in STRONG_SYNTHETIC_SOURCE_TERMS)


def _source_only_audio_result(
    url: str,
    discovery: dict[str, Any],
    error_message: Optional[str] = None,
) -> dict[str, Any]:
    source_credibility = analyze_source_credibility(url)
    source_score = float(source_credibility.get("score") or 0.5)
    high_risk_source = bool(source_credibility.get("risky_match")) or source_score <= 0.24
    fake_probability = round(clamp(0.62 if high_risk_source else 0.34, 0.18, 0.82), 4)
    real_probability = round(1.0 - fake_probability, 4)
    prediction = "FAKE" if high_risk_source else "REAL"
    status = "Fake" if prediction == "FAKE" else "Real"
    confidence = 0.52 if error_message else 0.55
    reasons = [
        "AI Shield could not retrieve a playable audio clip, so this assessment is based on source-level signals only.",
        *(discovery.get("discovery_notes") or []),
        *(source_credibility.get("reasons") or [])[:2],
    ]
    if error_message:
        reasons.append(f"Fetch detail: {error_message}")

    return {
        "analysis_type": "audio_url",
        "content_type": "audio",
        "status": status,
        "prediction": prediction,
        "fake_probability": fake_probability,
        "real_probability": real_probability,
        "confidence": confidence,
        "summary": (
            f"AI Shield classified the audio URL as {status.lower()} with "
            f"{int(round((fake_probability if prediction == 'FAKE' else real_probability) * 100))}% support using source-level signals only."
        ),
        "reasons": reasons,
        "explanation": reasons,
        "model": {
            "mode": "source-only-voice-fallback",
            "cnn_ready": 0,
            "lstm_ready": 0,
            "transformer_ready": 0,
        },
        "audio_forensics": {
            "feature_extractor": "source-only",
            "suspicious_regions": [],
            "breathing_segments": [],
            "signals": {
                "source_only": 1,
                "download_available": 0,
            },
            "branch_scores": {},
        },
        "source_credibility": source_credibility,
        "metadata": {
            "source_url": url,
            "resolved_audio_url": discovery.get("download_url"),
            "download_mode": discovery.get("mode"),
            "download_available": 0,
            "source_only_assessment": 1,
        },
    }


def _should_keep_fake_voice_url_result(result: dict[str, Any], *, original_name: str) -> bool:
    metadata = result.get("metadata", {}) or {}
    fake_probability = float(result.get("fake_probability") or 0.0)
    confidence = float(result.get("confidence") or 0.0)
    synthetic_support = float(metadata.get("synthetic_support_score", 0.0) or 0.0)
    branch_scores = ((result.get("audio_forensics") or {}).get("branch_scores") or {})
    branch_peak = max((float(value or 0.0) for value in branch_scores.values()), default=0.0)

    return (
        _has_strong_synthetic_name(original_name)
        or synthetic_support >= 0.72
        or fake_probability >= 0.82
        or (fake_probability >= 0.72 and confidence >= 0.9 and (synthetic_support >= 0.6 or branch_peak >= 0.82))
    )


def _apply_conservative_voice_url_adjustment(
    result: dict[str, Any],
    *,
    discovery: dict[str, Any],
    original_name: str,
) -> dict[str, Any]:
    if result.get("prediction") != "FAKE":
        result.setdefault("metadata", {})
        result["metadata"]["url_conservative_override"] = 0
        return result

    if _should_keep_fake_voice_url_result(result, original_name=original_name):
        result.setdefault("metadata", {})
        result["metadata"]["url_conservative_override"] = 0
        return result

    fake_probability_before = float(result.get("fake_probability") or 0.0)
    confidence_before = float(result.get("confidence") or 0.0)
    mode = str(discovery.get("mode") or "source-only")
    allow_override = False
    if mode == "direct":
        allow_override = fake_probability_before < 0.64 and confidence_before < 0.88
    else:
        allow_override = fake_probability_before < 0.74

    if not allow_override:
        result.setdefault("metadata", {})
        result["metadata"]["url_conservative_override"] = 0
        return result

    fake_probability = round(
        clamp(
            0.33 + (0.03 if mode != "direct" else 0.0),
            0.2,
            0.49,
        ),
        4,
    )
    result["status"] = "Real"
    result["prediction"] = "REAL"
    result["fake_probability"] = fake_probability
    result["real_probability"] = round(1.0 - fake_probability, 4)
    result["confidence"] = round(min(float(result.get("confidence") or 0.58), 0.58), 4)
    result["summary"] = (
        "AI Shield treated this audio URL as real because the downloadable clip did not show strong enough "
        "AI-only voice evidence for a reliable fake decision in URL mode."
    )
    result["reasons"] = [
        "URL mode found only weak or mixed synthetic-voice signals, so AI Shield used a conservative real-side decision for this downloadable clip.",
        *(result.get("reasons") or []),
    ]
    result["explanation"] = result["reasons"]
    result.setdefault("metadata", {})
    result["metadata"]["url_conservative_override"] = 1
    return result


def analyze_voice_url_input(url: str, uploads_dir: str, timeout_seconds: float = 8.0) -> dict[str, Any]:
    normalized_url = url.strip()
    _validate_http_url(normalized_url)
    if _is_streaming_platform(normalized_url):
        return _source_only_audio_result(
            normalized_url,
            {"download_url": None, "mode": "source-only", "discovery_notes": []},
            error_message=_friendly_voice_url_error(normalized_url, ValueError("streaming platform")),
        )

    runtime_timeout = _runtime_timeout(timeout_seconds)
    LOGGER.info("voice_url_analysis_start url=%s timeout=%s", normalized_url, runtime_timeout)
    try:
        discovery = dict(_cached_discovery(normalized_url, runtime_timeout))
    except Exception as error:
        LOGGER.warning("voice_url_discovery_failed url=%s error=%s", normalized_url, error)
        return _source_only_audio_result(
            normalized_url,
            {"download_url": None, "mode": "source-only", "discovery_notes": []},
            error_message=_friendly_voice_url_error(normalized_url, error),
        )
    download_url = discovery.get("download_url")
    LOGGER.info(
        "voice_url_discovery url=%s mode=%s download_available=%s",
        normalized_url,
        discovery.get("mode"),
        int(bool(download_url)),
    )
    if not download_url:
        return _source_only_audio_result(
            normalized_url,
            discovery,
            error_message=(
                "AI Shield could not resolve a downloadable audio stream from this URL. "
                "Use a direct audio link or upload the audio file."
            ),
        )

    try:
        downloaded = _download_audio(str(download_url), uploads_dir=uploads_dir, timeout_seconds=runtime_timeout)
    except Exception as error:
        LOGGER.warning("voice_url_download_failed url=%s resolved_url=%s error=%s", normalized_url, download_url, error)
        return _source_only_audio_result(
            normalized_url,
            discovery,
            error_message=_friendly_voice_url_error(str(download_url), error),
        )
    LOGGER.info(
        "voice_url_download url=%s resolved_url=%s bytes=%s truncated=%s content_type=%s content_valid=%s",
        normalized_url,
        download_url,
        downloaded.get("downloaded_bytes"),
        downloaded.get("truncated"),
        downloaded.get("content_type"),
        downloaded.get("content_valid"),
    )
    if downloaded.get("truncated"):
        return _source_only_audio_result(
            normalized_url,
            discovery,
            error_message=(
                "The linked audio was too large for lightweight URL mode and only a partial download was available. "
                "Upload the full audio file for reliable analysis."
            ),
        )
    if not downloaded.get("content_valid"):
        raise ValueError(str(downloaded.get("validation_reason") or "AI Shield could not validate a playable audio file from this URL."))

    neutral_name = _neutral_audio_name(downloaded["original_name"])
    result = analyze_audio(downloaded["path"], neutral_name)
    result["analysis_type"] = "audio_url"
    result["input_name"] = normalized_url
    result.setdefault("metadata", {})

    result["metadata"].update(
        {
            "source_url": normalized_url,
            "resolved_audio_url": download_url,
            "resolved_audio_name": downloaded["original_name"],
            "analysis_filename": neutral_name,
            "download_mode": discovery.get("mode"),
            "downloaded_bytes": downloaded.get("downloaded_bytes"),
            "download_truncated": int(bool(downloaded.get("truncated"))),
            "limited_url_context": int(discovery.get("mode") != "direct"),
            "download_content_type": downloaded.get("content_type"),
            "download_content_valid": int(bool(downloaded.get("content_valid"))),
            "download_validation_reason": downloaded.get("validation_reason", ""),
            "download_head_signature": downloaded.get("head_signature", ""),
            "fast_mode": int(_voice_fast_mode_enabled()),
            "runtime_timeout_seconds": runtime_timeout,
            "url_debug": {
                "input_url": normalized_url,
                "resolved_audio_url": download_url,
                "discovery_mode": discovery.get("mode"),
                "downloaded_bytes": downloaded.get("downloaded_bytes"),
                "download_content_type": downloaded.get("content_type"),
                "download_content_valid": int(bool(downloaded.get("content_valid"))),
                "download_validation_reason": downloaded.get("validation_reason", ""),
                "analysis_filename": neutral_name,
                "model_input_sample_rate": result["metadata"].get("sample_rate"),
                "model_input_duration_seconds": result["metadata"].get("duration_seconds"),
            },
        }
    )
    notes = list(discovery.get("discovery_notes") or [])
    if notes:
        result["reasons"] = [*notes, *(result.get("reasons") or [])]
        result["explanation"] = result["reasons"]
    LOGGER.info(
        "voice_url_prediction url=%s prediction=%s fake_probability=%s confidence=%s sample_rate=%s",
        normalized_url,
        result.get("prediction"),
        result.get("fake_probability"),
        result.get("confidence"),
        result["metadata"].get("sample_rate"),
    )
    result["metadata"]["url_conservative_override"] = 0
    return result
