from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4

import requests
from requests import exceptions as request_exceptions

from backend.models.deepfake_video_model import analyze_video
from backend.services.source_credibility_service import analyze_source_credibility
from backend.utils.file_handler import ensure_runtime_dirs
from backend.utils.scoring import clamp, filename_terms, FAKE_FILENAME_TERMS


LOGGER = logging.getLogger(__name__)
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
VIDEO_URL_HINTS = ("video", ".mp4", ".mov", ".avi", ".mkv", ".webm", "stream", "clip")
HTML_VIDEO_PATTERNS = (
    re.compile(r'<meta[^>]+property=["\']og:video(?::url)?["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<video[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE),
    re.compile(r'<source[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE),
)
TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TITLE_FAKE_PATTERNS = (
    (re.compile(r"\bai[- ]generated\b", re.IGNORECASE), 0.52, "The page title explicitly says the video is AI-generated."),
    (re.compile(r"\bai video\b", re.IGNORECASE), 0.42, "The page title explicitly labels the clip as an AI video."),
    (re.compile(r"\bdeepfake\b", re.IGNORECASE), 0.52, "The page title explicitly labels the clip as a deepfake."),
    (re.compile(r"\bnot a real person\b", re.IGNORECASE), 0.44, "The page title says the person shown is not real."),
    (
        re.compile(r"\b(veo\s*3|veo3|sora|runway|pika|heygen|synthesia)\b", re.IGNORECASE),
        0.24,
        "The page title references a known generative-video platform.",
    ),
)
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
MAX_VIDEO_DOWNLOAD_BYTES = 80 * 1024 * 1024
MIN_VIDEO_DOWNLOAD_BYTES = 4 * 1024
FAST_VIDEO_TIMEOUT_SECONDS = 3.0
YT_DLP_TIMEOUT_SECONDS = 18
YT_DLP_DOWNLOAD_TIMEOUT_SECONDS = 24
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
        raise ValueError("AI Shield requires a valid http or https video URL.")


def _guess_filename(url: str, response: Optional[requests.Response] = None) -> str:
    if response is not None:
        disposition = response.headers.get("content-disposition", "")
        match = re.search(r'filename="?([^";]+)"?', disposition, re.IGNORECASE)
        if match:
            return match.group(1)

    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name or "video.mp4"
    return name if Path(name).suffix.lower() in VIDEO_EXTENSIONS else f"{name}.mp4"


def _looks_like_direct_video(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in VIDEO_URL_HINTS) or Path(urlparse(url).path).suffix.lower() in VIDEO_EXTENSIONS


def _video_fast_mode_enabled() -> bool:
    return os.getenv("AI_SHIELD_FAST_MODE", "true").lower() != "false"


def _runtime_timeout(timeout_seconds: float) -> float:
    if not _video_fast_mode_enabled():
        return float(timeout_seconds)
    return min(float(timeout_seconds), FAST_VIDEO_TIMEOUT_SECONDS)


def _streaming_deep_forensics_enabled() -> bool:
    return os.getenv("AI_SHIELD_ANALYZE_STREAMING_VIDEO", "false").lower() == "true"


def _extract_title(html: str) -> str:
    match = TITLE_PATTERN.search(html)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _video_title_fake_signal(title: str) -> dict[str, Any]:
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    if not cleaned:
        return {"score": 0.0, "terms": [], "reasons": []}

    score = 0.0
    reasons: list[str] = []
    for pattern, weight, reason in TITLE_FAKE_PATTERNS:
        if pattern.search(cleaned):
            score += weight
            if reason not in reasons:
                reasons.append(reason)

    matched_terms = filename_terms(cleaned, FAKE_FILENAME_TERMS)
    if matched_terms:
        score += min(len(matched_terms) * 0.08, 0.2)
        reasons.append("The page title contains fake-content terms associated with AI-generated media.")

    lowered = cleaned.lower()
    if ("ai" in lowered or "generated" in lowered) and ("video" in lowered or "person" in lowered or "human" in lowered):
        score += 0.16
        reasons.append("The page title combines AI-generation language with a direct video or person claim.")

    return {
        "score": round(clamp(score, 0.0, 1.0), 2),
        "terms": matched_terms,
        "reasons": reasons[:3],
    }


def _apply_title_based_video_adjustment(result: dict[str, Any], page_title: str) -> dict[str, Any]:
    title_signal = _video_title_fake_signal(page_title)
    result.setdefault("metadata", {})
    result["metadata"]["title_fake_signal_score"] = title_signal["score"]
    result["metadata"]["title_fake_terms"] = title_signal["terms"]
    result["metadata"]["title_fake_reasons"] = title_signal["reasons"]

    if title_signal["score"] < 0.58:
        return result

    fake_probability_before = float(result.get("fake_probability") or 0.0)
    strengthened_probability = round(max(fake_probability_before, clamp(0.68 + title_signal["score"] * 0.18, 0.68, 0.92)), 2)

    result["status"] = "Fake"
    result["prediction"] = "FAKE"
    result["fake_probability"] = strengthened_probability
    result["real_probability"] = round(1 - strengthened_probability, 2)
    result["confidence"] = max(float(result.get("confidence") or 0.62), 0.88 if title_signal["score"] < 0.82 else 0.92)
    forensics_available = int((result.get("metadata") or {}).get("forensics_available", 0) or 0)
    if forensics_available:
        result["summary"] = (
            "AI Shield classified this URL video as fake because the downloaded clip was analyzed and the source title "
            "also contains strong AI-generation cues."
        )
    else:
        result["summary"] = (
            "AI Shield classified this URL video as fake because the source title contains strong AI-generation cues."
        )
    merged_reasons = [*title_signal["reasons"], *(result.get("reasons") or [])]
    deduped: list[str] = []
    for item in merged_reasons:
        if item not in deduped:
            deduped.append(item)
    result["reasons"] = deduped
    result["explanation"] = deduped
    result["metadata"]["title_based_override"] = 1
    return result


def _is_streaming_platform(url: str) -> bool:
    domain = (urlparse(url).netloc or "").lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == item or domain.endswith(f".{item}") for item in STREAMING_PLATFORM_DOMAINS)


def _friendly_video_url_error(url: str, error: Exception) -> str:
    if _is_streaming_platform(url):
        return (
            "This link is from a streaming platform like YouTube. "
            "AI Shield URL mode cannot reliably extract the live stream directly in this lightweight runtime. "
            "Use a direct MP4 link or upload the video file for full analysis."
        )
    if isinstance(error, request_exceptions.Timeout):
        return "The source took too long to respond. Try again, use a direct MP4 link, or upload the video file."
    if isinstance(error, request_exceptions.ConnectionError):
        return "AI Shield could not connect to this video source right now. Try again or upload the video file."
    return "AI Shield could not fetch a playable video stream from this URL right now."


def _looks_like_html_payload(sample: bytes) -> bool:
    lowered = sample.lstrip().lower()
    return any(marker in lowered[:512] for marker in HTML_PAYLOAD_MARKERS)


def _looks_like_video_payload(sample: bytes) -> bool:
    prefix = sample[:256]
    return (
        b"ftyp" in prefix[:64]
        or prefix.startswith(b"\x1a\x45\xdf\xa3")
        or prefix.startswith(b"RIFF")
        or b"moov" in prefix
        or b"mdat" in prefix
    )


def _yt_dlp_path() -> Optional[str]:
    discovered = shutil.which("yt-dlp")
    if discovered:
        return discovered

    for candidate in ("/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"):
        if Path(candidate).exists():
            return candidate
    return None


def _resolve_streaming_video_with_yt_dlp(url: str, timeout_seconds: float) -> Optional[dict[str, Any]]:
    yt_dlp = _yt_dlp_path()
    if not yt_dlp:
        return None

    command = [
        yt_dlp,
        "--dump-single-json",
        "--no-playlist",
        "--no-warnings",
        "--format",
        "best[ext=mp4]/best",
        url,
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(int(timeout_seconds), YT_DLP_TIMEOUT_SECONDS),
            check=True,
        )
    except Exception as error:
        LOGGER.warning("video_url_ytdlp_failed url=%s error=%s", url, error)
        return None

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return None

    direct_url = str(payload.get("url") or "").strip()
    if not direct_url:
        formats = payload.get("formats") or []
        for item in reversed(formats):
            candidate = str(item.get("url") or "").strip()
            if candidate.startswith("http"):
                direct_url = candidate
                break

    if not direct_url.startswith("http"):
        return None

    return {
        "download_url": direct_url,
        "mode": "stream-extracted",
        "page_title": str(payload.get("title") or "").strip(),
        "duration_seconds": payload.get("duration"),
        "uploader": str(payload.get("uploader") or payload.get("channel") or "").strip(),
        "webpage_url": str(payload.get("webpage_url") or url).strip(),
        "content_type": "video/mp4",
        "discovery_notes": ["A streaming-platform URL was resolved to a downloadable video stream using yt-dlp."],
    }


def _discover_video_asset(url: str, timeout_seconds: float) -> dict[str, Any]:
    if _is_streaming_platform(url):
        resolved_stream = _resolve_streaming_video_with_yt_dlp(url, timeout_seconds=max(timeout_seconds, YT_DLP_TIMEOUT_SECONDS))
        if resolved_stream:
            return resolved_stream
        return {
            "download_url": None,
            "mode": "streaming-platform-unsupported",
            "page_title": "",
            "content_type": "text/html",
            "discovery_notes": [
                "This URL belongs to a streaming platform like YouTube, but yt-dlp is not available to extract the real video stream in this runtime."
            ],
        }

    response = requests.get(url, timeout=(2.5, timeout_seconds), headers=REQUEST_HEADERS, allow_redirects=True)
    response.raise_for_status()

    content_type = (response.headers.get("content-type") or "").lower()
    final_url = str(response.url)
    if content_type.startswith("video/") or _looks_like_direct_video(final_url):
        return {
            "download_url": final_url,
            "mode": "direct",
            "page_title": "",
            "content_type": content_type,
            "discovery_notes": ["The submitted URL points directly to a video resource."],
        }

    html = response.text[:400_000]
    page_title = _extract_title(html)
    for pattern in HTML_VIDEO_PATTERNS:
        match = pattern.search(html)
        if match:
            candidate = urljoin(final_url, match.group(1).strip())
            return {
                "download_url": candidate,
                "mode": "embedded",
                "page_title": page_title,
                "content_type": content_type or "text/html",
                "discovery_notes": ["A playable video URL was discovered from page metadata."],
            }

    return {
        "download_url": None,
        "mode": "source-only",
        "page_title": page_title,
        "content_type": content_type or "text/html",
        "discovery_notes": ["No downloadable video stream was exposed by the submitted page."],
    }


@lru_cache(maxsize=32)
def _cached_discovery(url: str, timeout_seconds: float) -> dict[str, Any]:
    return dict(_discover_video_asset(url, timeout_seconds))


@lru_cache(maxsize=32)
def _cached_source_credibility(url: str) -> dict[str, Any]:
    return dict(analyze_source_credibility(url))


def _download_video(url: str, uploads_dir: str, timeout_seconds: float) -> dict[str, Any]:
    bucket = Path(uploads_dir) / "video-url"
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
            if next_size > MAX_VIDEO_DOWNLOAD_BYTES:
                allowed_bytes = MAX_VIDEO_DOWNLOAD_BYTES - downloaded_bytes
                if allowed_bytes > 0:
                    handle.write(chunk[:allowed_bytes])
                    downloaded_bytes += allowed_bytes
                truncated = True
                break

            handle.write(chunk)
            downloaded_bytes = next_size

    content_type = (response.headers.get("content-type") or "").lower()
    html_like = _looks_like_html_payload(bytes(head_sample))
    media_like = _looks_like_video_payload(bytes(head_sample))
    content_valid = True
    validation_reason = ""
    if downloaded_bytes < MIN_VIDEO_DOWNLOAD_BYTES:
        content_valid = False
        validation_reason = "The resolved URL returned too little data to validate a playable video clip."
    elif html_like:
        content_valid = False
        validation_reason = "The resolved URL returned an HTML page instead of a video file."
    elif not content_type.startswith("video/") and not media_like:
        content_valid = False
        validation_reason = "The resolved URL did not return a recognizable video payload."

    return {
        "path": str(stored_path),
        "original_name": original_name,
        "downloaded_bytes": downloaded_bytes,
        "truncated": truncated,
        "content_type": content_type,
        "content_valid": int(content_valid),
        "validation_reason": validation_reason,
        "head_signature": bytes(head_sample[:64]).decode("latin1", errors="ignore"),
        "download_method": "requests",
    }


def _download_streaming_video_with_yt_dlp(url: str, uploads_dir: str, timeout_seconds: float) -> dict[str, Any]:
    yt_dlp = _yt_dlp_path()
    if not yt_dlp:
        raise ValueError(
            "AI Shield cannot directly analyze YouTube or Shorts links in this runtime because the stream extractor is not installed. "
            "Upload the video file, use a direct MP4 link, or install yt-dlp for streaming URL support."
        )

    bucket = Path(uploads_dir) / "video-url"
    ensure_runtime_dirs(str(bucket))
    target_dir = bucket / uuid4().hex
    ensure_runtime_dirs(str(target_dir))
    output_template = str(target_dir / "clip.%(ext)s")

    command = [
        yt_dlp,
        "--quiet",
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout",
        "6",
        "--retries",
        "1",
        "--fragment-retries",
        "1",
        "--format",
        "worst[ext=mp4]/worst",
        "--output",
        output_template,
        url,
    ]
    LOGGER.info("video_url_ytdlp_download_start url=%s output=%s", url, output_template)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(int(timeout_seconds), YT_DLP_DOWNLOAD_TIMEOUT_SECONDS),
            check=True,
        )
    except subprocess.TimeoutExpired as error:
        LOGGER.warning("video_url_ytdlp_download_timeout url=%s error=%s", url, error)
        raise ValueError("The streaming video download took too long. Try again or upload the video file.") from error
    except subprocess.CalledProcessError as error:
        stderr = (error.stderr or "").strip()
        LOGGER.warning("video_url_ytdlp_download_failed url=%s error=%s", url, stderr or error)
        raise ValueError(
            "AI Shield could not download a playable video stream from this URL. Try again or upload the video file."
        ) from error

    candidates = [
        path
        for path in target_dir.iterdir()
        if path.is_file() and path.suffix.lower() not in {".part", ".tmp", ".ytdl"}
    ]
    if not candidates:
        LOGGER.warning("video_url_ytdlp_download_empty url=%s stdout=%s", url, (completed.stdout or "").strip())
        raise ValueError("AI Shield could not save a playable video file from this streaming URL.")

    stored_path = max(candidates, key=lambda item: item.stat().st_size)
    downloaded_bytes = int(stored_path.stat().st_size)
    head_sample = stored_path.read_bytes()[:4096]
    html_like = _looks_like_html_payload(head_sample)
    media_like = _looks_like_video_payload(head_sample)
    content_valid = True
    validation_reason = ""
    if downloaded_bytes < MIN_VIDEO_DOWNLOAD_BYTES:
        content_valid = False
        validation_reason = "The resolved URL returned too little data to validate a playable video clip."
    elif html_like:
        content_valid = False
        validation_reason = "The resolved URL returned an HTML page instead of a video file."
    elif not media_like and stored_path.suffix.lower() not in VIDEO_EXTENSIONS:
        content_valid = False
        validation_reason = "The resolved URL did not return a recognizable video payload."

    LOGGER.info(
        "video_url_ytdlp_download_success url=%s path=%s bytes=%s content_valid=%s",
        url,
        stored_path,
        downloaded_bytes,
        int(content_valid),
    )
    return {
        "path": str(stored_path),
        "original_name": stored_path.name,
        "downloaded_bytes": downloaded_bytes,
        "truncated": False,
        "content_type": "video/mp4",
        "content_valid": int(content_valid),
        "validation_reason": validation_reason,
        "head_signature": head_sample[:64].decode("latin1", errors="ignore"),
        "download_method": "yt-dlp",
    }


def _neutral_video_name(original_name: str) -> str:
    suffix = Path(original_name).suffix.lower() or ".mp4"
    if suffix not in VIDEO_EXTENSIONS:
        suffix = ".mp4"
    return f"url_video_sample{suffix}"


def _should_keep_fake_video_url_result(
    result: dict[str, Any],
    *,
    source_credibility: dict[str, Any],
) -> bool:
    metadata = result.get("metadata", {}) or {}
    prediction_trace = metadata.get("prediction_trace") or {}
    signals = ((result.get("video_forensics") or {}).get("signals") or {})
    source_score = float(source_credibility.get("score") or 0.5)
    high_risk_source = bool(source_credibility.get("risky_match")) or source_score <= 0.24
    fake_probability = float(result.get("fake_probability") or 0.0)
    confidence = float(result.get("confidence") or 0.0)
    generation_marker_score = float(signals.get("generation_marker_score", metadata.get("generation_marker_score", 0.0)) or 0.0)
    suspicious_segment_count = int(signals.get("suspicious_segment_count", metadata.get("suspicious_window_count", 0)) or 0)
    suspicious_frame_count = int(signals.get("suspicious_frame_count", metadata.get("suspicious_frame_count", 0)) or 0)
    facial_inconsistency = float(signals.get("facial_inconsistency_proxy", 0.0) or 0.0)
    lip_sync = float(signals.get("lip_sync_proxy", 0.0) or 0.0)
    temporal_consistency = float(signals.get("temporal_consistency_proxy", 0.0) or 0.0)
    visual_artifact = float(signals.get("visual_artifact_proxy", metadata.get("visual_artifact_proxy", 0.0)) or 0.0)
    frozen_speech = float(signals.get("frozen_speech_proxy", metadata.get("frozen_speech_proxy", 0.0)) or 0.0)
    low_quality_proxy = float(signals.get("low_quality_proxy", metadata.get("low_quality_proxy", 0.0)) or 0.0)
    frozen_speech_bundle = bool(
        signals.get("frozen_speech_bundle")
        or prediction_trace.get("frozen_speech_bundle")
    )
    compression_low_quality_relief = bool(prediction_trace.get("compression_low_quality_relief"))
    ai_export_markers = metadata.get("ai_export_markers") or []

    strong_forensics = (
        bool(ai_export_markers)
        or generation_marker_score >= 0.32
        or visual_artifact >= 0.35
        or (frozen_speech >= 0.62 and frozen_speech_bundle)
        or suspicious_segment_count >= 2
        or suspicious_frame_count >= 2
    )
    coupled_motion_signals = temporal_consistency >= 0.45 and (facial_inconsistency >= 0.35 or lip_sync >= 0.32)
    strong_model = fake_probability >= 0.82 or (fake_probability >= 0.72 and confidence >= 0.9 and (strong_forensics or coupled_motion_signals))
    weak_low_quality_case = bool(
        compression_low_quality_relief
        or (
            low_quality_proxy >= 0.42
            and not ai_export_markers
            and generation_marker_score < 0.18
            and visual_artifact < 0.58
            and suspicious_segment_count <= 1
            and suspicious_frame_count <= 1
            and not frozen_speech_bundle
        )
    )

    if high_risk_source and fake_probability >= 0.72:
        return True
    if weak_low_quality_case and not strong_forensics and not coupled_motion_signals and fake_probability < 0.78:
        return False
    return strong_forensics or coupled_motion_signals or strong_model


def _apply_conservative_video_url_adjustment(
    result: dict[str, Any],
    *,
    source_credibility: dict[str, Any],
    discovery: dict[str, Any],
) -> dict[str, Any]:
    if result.get("prediction") != "FAKE":
        result.setdefault("metadata", {})
        result["metadata"]["url_conservative_override"] = 0
        return result

    if _should_keep_fake_video_url_result(result, source_credibility=source_credibility):
        result.setdefault("metadata", {})
        result["metadata"]["url_conservative_override"] = 0
        return result

    source_score = float(source_credibility.get("score") or 0.5)
    fake_probability_before = float(result.get("fake_probability") or 0.0)
    confidence_before = float(result.get("confidence") or 0.0)
    mode = str(discovery.get("mode") or "source-only")
    metadata = result.get("metadata", {}) or {}
    prediction_trace = metadata.get("prediction_trace") or {}
    low_quality_proxy = float(metadata.get("low_quality_proxy", 0.0) or 0.0)
    compression_low_quality_relief = bool(prediction_trace.get("compression_low_quality_relief"))
    allow_override = False
    if mode == "direct":
        allow_override = False
    else:
        allow_override = fake_probability_before < 0.72

    if compression_low_quality_relief or low_quality_proxy >= 0.42:
        allow_override = allow_override or fake_probability_before < 0.74

    if not allow_override:
        result.setdefault("metadata", {})
        result["metadata"]["url_conservative_override"] = 0
        return result

    fake_probability = round(
        clamp(
            0.36 + max(0.0, 0.5 - source_score) * 0.16 + (0.03 if mode != "direct" else 0.0),
            0.22,
            0.49,
        ),
        2,
    )
    result["status"] = "Real"
    result["prediction"] = "REAL"
    result["fake_probability"] = fake_probability
    result["real_probability"] = round(1 - fake_probability, 2)
    result["confidence"] = round(min(float(result.get("confidence") or 0.58), 0.58), 2)
    result["summary"] = (
        "AI Shield treated this URL video as real because the downloaded clip did not show strong enough "
        "deepfake-only forensic evidence for a reliable fake decision in URL mode."
    )
    result["reasons"] = [
        "URL mode found only weak or mixed fake signals, so AI Shield used a conservative real-side decision for this downloadable clip.",
        *(result.get("reasons") or []),
    ]
    result["explanation"] = result["reasons"]
    result.setdefault("metadata", {})
    result["metadata"]["url_conservative_override"] = 1
    return result


def _source_only_video_result(
    url: str,
    source_credibility: dict[str, Any],
    discovery: dict[str, Any],
    error_message: Optional[str] = None,
) -> dict[str, Any]:
    source_score = float(source_credibility.get("score") or 0.5)
    risky_match = bool(source_credibility.get("risky_match"))
    very_low_trust = source_score <= 0.28
    high_risk_source = risky_match or very_low_trust

    if high_risk_source:
        fake_probability = round(clamp(0.62 + max(0.0, 0.38 - source_score) * 0.45, 0.56, 0.82), 2)
    else:
        fake_probability = round(clamp(0.46 + (0.5 - source_score) * 0.18, 0.32, 0.58), 2)
    real_probability = round(1 - fake_probability, 2)
    confidence = 0.51 if error_message else 0.55
    status = "Fake" if high_risk_source and fake_probability >= 0.6 else "Real"
    prediction = "FAKE" if status == "Fake" else "REAL"

    reasons = [
        "AI Shield could not retrieve a playable video clip, so this assessment is based on source-level signals only.",
        *discovery.get("discovery_notes", []),
        *source_credibility.get("reasons", [])[:2],
    ]
    if error_message:
        reasons.append(f"Fetch detail: {error_message}")

    summary = (
        f"AI Shield classified the submitted video link as {status.lower()} with "
        f"{int(fake_probability * 100)}% fake probability using source credibility signals only."
    )
    unavailable_reason = (
        error_message
        or "A downloadable video clip was not exposed by this URL, so frame-level deepfake forensics were not available."
    )

    return {
        "analysis_type": "video_url",
        "content_type": "video",
        "input_name": url,
        "status": status,
        "prediction": prediction,
        "fake_probability": fake_probability,
        "real_probability": real_probability,
        "confidence": confidence,
        "summary": summary,
        "reasons": reasons,
        "explanation": reasons,
        "source_credibility": source_credibility,
        "video_forensics": {
            "frame_sampling_mode": "source-only",
            "forensics_available": 0,
            "unavailable_reason": unavailable_reason,
            "suspicious_segments": [],
            "signals": {
                "download_available": 0,
                "source_only": 1,
                "forensics_available": 0,
            },
        },
        "metadata": {
            "source_url": url,
            "resolved_video_url": discovery.get("download_url"),
            "download_mode": discovery.get("mode"),
            "page_title": discovery.get("page_title"),
            "source_score": source_score,
            "download_available": 0,
            "source_only_assessment": 1,
            "forensics_available": 0,
            "forensics_unavailable_reason": unavailable_reason,
        },
    }


def _apply_streaming_fast_real_boost(
    result: dict[str, Any],
    *,
    source_credibility: dict[str, Any],
    discovery: dict[str, Any],
) -> dict[str, Any]:
    source_score = float(source_credibility.get("score") or 0.5)
    title_signal = _video_title_fake_signal(str(discovery.get("page_title") or ""))
    risky_source = bool(source_credibility.get("risky_match")) or source_score <= 0.35
    result.setdefault("metadata", {})

    if result.get("prediction") != "REAL" or risky_source or title_signal["score"] >= 0.58:
        result["metadata"]["streaming_real_probability_boost"] = 0
        return result

    if source_score >= 0.58:
        fake_probability = 0.14
        confidence = 0.86
    elif source_score >= 0.5:
        fake_probability = 0.2
        confidence = 0.82
    else:
        fake_probability = 0.28
        confidence = 0.74

    real_probability = round(1 - fake_probability, 2)
    result["fake_probability"] = fake_probability
    result["real_probability"] = real_probability
    result["confidence"] = confidence
    result["summary"] = (
        f"AI Shield classified this streaming video link as real with "
        f"{int(real_probability * 100)}% real probability using source credibility and neutral title signals."
    )
    result["reasons"] = [
        "The streaming source and title did not contain AI-generation or deepfake cues, so fast mode assigned stronger real-side confidence.",
        *(result.get("reasons") or []),
    ]
    result["explanation"] = result["reasons"]
    result["metadata"]["streaming_real_probability_boost"] = 1
    result["metadata"]["confidence_basis"] = "streaming-source-fast-path"
    return result


def analyze_video_url_input(url: str, uploads_dir: str, timeout_seconds: float = 8.0) -> dict[str, Any]:
    normalized_url = url.strip()
    _validate_http_url(normalized_url)
    runtime_timeout = _runtime_timeout(timeout_seconds)
    LOGGER.info("video_url_analysis_start url=%s timeout=%s", normalized_url, runtime_timeout)
    source_credibility = _cached_source_credibility(normalized_url)

    try:
        discovery = _cached_discovery(normalized_url, runtime_timeout)
    except Exception as error:
        LOGGER.warning("video_url_discovery_failed url=%s error=%s", normalized_url, error)
        return _source_only_video_result(
            normalized_url,
            source_credibility,
            {"download_url": None, "mode": "source-only", "page_title": "", "discovery_notes": []},
            error_message=_friendly_video_url_error(normalized_url, error),
        )

    download_url = discovery.get("download_url")
    LOGGER.info(
        "video_url_discovery url=%s mode=%s download_available=%s content_type=%s",
        normalized_url,
        discovery.get("mode"),
        int(bool(download_url)),
        discovery.get("content_type", ""),
    )
    if discovery.get("mode") == "streaming-platform-unsupported":
        raise ValueError(
            "AI Shield cannot directly analyze YouTube or Shorts links in this runtime because the stream extractor is not installed. "
            "Upload the video file, use a direct MP4 link, or install yt-dlp for streaming URL support."
        )
    if not download_url:
        return _source_only_video_result(normalized_url, source_credibility, discovery)

    download_mode = str(discovery.get("mode") or "")
    if download_mode == "stream-extracted" and not _streaming_deep_forensics_enabled():
        result = _source_only_video_result(
            normalized_url,
            source_credibility,
            discovery,
            error_message=(
                "Streaming-platform fast mode skipped the full video download to avoid slow processing and "
                "false positives from YouTube/Shorts compression. Upload the video file or set "
                "AI_SHIELD_ANALYZE_STREAMING_VIDEO=true for slower frame-level analysis."
            ),
        )
        result.setdefault("metadata", {})
        result["metadata"].update(
            {
                "download_mode": discovery.get("mode"),
                "streaming_platform_fast_path": 1,
                "streaming_deep_forensics_enabled": 0,
                "uploader": discovery.get("uploader", ""),
                "source_duration_seconds": discovery.get("duration_seconds"),
                "webpage_url": discovery.get("webpage_url", normalized_url),
                "fast_mode": int(_video_fast_mode_enabled()),
                "runtime_timeout_seconds": runtime_timeout,
                "forensics_available": 0,
            }
        )
        result["reasons"] = [
            "YouTube/Shorts links are handled conservatively in fast mode because platform compression can look suspicious to lightweight frame heuristics.",
            *(result.get("reasons") or []),
        ]
        result["explanation"] = result["reasons"]
        result = _apply_streaming_fast_real_boost(
            result,
            source_credibility=source_credibility,
            discovery=discovery,
        )
        result = _apply_title_based_video_adjustment(result, str(discovery.get("page_title") or ""))
        result["metadata"].setdefault("url_conservative_override", 1)
        return result

    try:
        if download_mode == "stream-extracted":
            downloaded = _download_streaming_video_with_yt_dlp(
                normalized_url,
                uploads_dir=uploads_dir,
                timeout_seconds=max(runtime_timeout, YT_DLP_TIMEOUT_SECONDS),
            )
        else:
            downloaded = _download_video(str(download_url), uploads_dir=uploads_dir, timeout_seconds=runtime_timeout)
    except Exception as error:
        LOGGER.warning("video_url_download_failed url=%s resolved_url=%s error=%s", normalized_url, download_url, error)
        return _source_only_video_result(
            normalized_url,
            source_credibility,
            discovery,
            error_message=_friendly_video_url_error(normalized_url, error),
        )

    LOGGER.info(
        "video_url_download url=%s resolved_url=%s bytes=%s truncated=%s content_type=%s content_valid=%s",
        normalized_url,
        download_url,
        downloaded.get("downloaded_bytes"),
        downloaded.get("truncated"),
        downloaded.get("content_type"),
        downloaded.get("content_valid"),
    )

    neutral_name = _neutral_video_name(str(downloaded["original_name"]))
    if downloaded.get("truncated"):
        return _source_only_video_result(
            normalized_url,
            source_credibility,
            discovery,
            error_message=(
                "The linked video was too large for lightweight URL mode and only a partial download was available. "
                "Upload the full video file for reliable analysis."
            ),
        )
    if not downloaded.get("content_valid"):
        raise ValueError(str(downloaded.get("validation_reason") or "AI Shield could not validate a playable video file from this URL."))

    result = analyze_video(
        downloaded["path"],
        neutral_name,
        source_url=None,
        source_credibility=None,
    )
    result["analysis_type"] = "video_url"
    result["input_name"] = normalized_url
    result["source_credibility"] = source_credibility

    result.setdefault("metadata", {})
    limited_url_context = discovery.get("mode") != "direct" or bool(downloaded.get("truncated"))
    result["metadata"].update(
        {
            "source_url": normalized_url,
            "resolved_video_url": download_url,
            "resolved_video_name": downloaded["original_name"],
            "analysis_filename": neutral_name,
            "page_title": discovery.get("page_title"),
            "download_mode": discovery.get("mode"),
            "downloaded_bytes": downloaded.get("downloaded_bytes"),
            "download_truncated": int(bool(downloaded.get("truncated"))),
            "limited_url_context": int(limited_url_context),
            "download_content_type": downloaded.get("content_type"),
            "download_content_valid": int(bool(downloaded.get("content_valid"))),
            "download_validation_reason": downloaded.get("validation_reason", ""),
            "download_head_signature": downloaded.get("head_signature", ""),
            "download_method": downloaded.get("download_method", "requests"),
            "streaming_platform_fast_path": 0,
            "streaming_deep_forensics_enabled": int(download_mode != "stream-extracted" or _streaming_deep_forensics_enabled()),
            "uploader": discovery.get("uploader", ""),
            "source_duration_seconds": discovery.get("duration_seconds"),
            "webpage_url": discovery.get("webpage_url", normalized_url),
            "download_available": 1,
            "fast_mode": int(_video_fast_mode_enabled()),
            "runtime_timeout_seconds": runtime_timeout,
            "url_debug": {
                "input_url": normalized_url,
                "resolved_video_url": download_url,
                "discovery_mode": discovery.get("mode"),
                "page_title": discovery.get("page_title"),
                "downloaded_bytes": downloaded.get("downloaded_bytes"),
                "download_content_type": downloaded.get("content_type"),
                "download_content_valid": int(bool(downloaded.get("content_valid"))),
                "download_validation_reason": downloaded.get("validation_reason", ""),
                "download_method": downloaded.get("download_method", "requests"),
                "analysis_filename": neutral_name,
                "model_input_sampled_frames": int(result["metadata"].get("sampled_frame_count", 0) or 0),
                "model_input_has_video_track": int(result["metadata"].get("has_video_track", 0) or 0),
                "model_input_has_audio_track": int(result["metadata"].get("has_audio_track", 0) or 0),
            },
        }
    )

    result.setdefault("video_forensics", {})
    result["video_forensics"]["forensics_available"] = 1
    result["video_forensics"]["signals"] = {
        **(result["video_forensics"].get("signals") or {}),
        "download_available": 1,
        "source_only": 0,
        "forensics_available": 1,
    }

    discovery_notes = discovery.get("discovery_notes", [])
    if discovery_notes:
        result["reasons"] = [*discovery_notes, *(result.get("reasons") or [])]
        result["explanation"] = result["reasons"]
    if downloaded.get("truncated"):
        result["reasons"].append(
            "The clip was capped to a short downloadable sample for low-latency analysis, so the score reflects a representative segment."
        )
        result["explanation"] = result["reasons"]
    result = _apply_conservative_video_url_adjustment(
        result,
        source_credibility=source_credibility,
        discovery=discovery,
    )
    result = _apply_title_based_video_adjustment(result, str(discovery.get("page_title") or ""))
    result["metadata"]["forensics_available"] = 1
    LOGGER.info(
        "video_url_prediction url=%s prediction=%s fake_probability=%s confidence=%s sampled_frames=%s",
        normalized_url,
        result.get("prediction"),
        result.get("fake_probability"),
        result.get("confidence"),
        result["metadata"].get("sampled_frame_count"),
    )
    result["metadata"].setdefault("url_conservative_override", 0)
    return result
