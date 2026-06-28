from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import create_app
from backend.database.report_db import store_report_metadata


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "DATABASE_PATH": str(tmp_path / "test.db"),
            "REPORTS_DIR": str(tmp_path / "reports"),
            "UPLOADS_DIR": str(tmp_path / "uploads"),
            "FRONTEND_DIR": str(PROJECT_ROOT / "frontend"),
        }
    )

    with app.test_client() as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_text_analysis_generates_report_bundle(client):
    response = client.post(
        "/api/news/analyze",
        json={"body": "Breaking! This shocking miracle claim is unbelievable!!!"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["analysis_type"] == "news_text"
    assert "pdf_url" in payload["report"]
    assert "csv_url" in payload["report"]

    pdf_response = client.get(payload["report"]["pdf_url"])
    csv_response = client.get(payload["report"]["csv_url"])
    assert pdf_response.status_code == 200
    assert csv_response.status_code == 200


def test_report_bundle_uses_integer_percentages(client):
    response = client.post(
        "/api/video/analyze",
        data={"video": (io.BytesIO(b"fake-video-content"), "sample.mp4")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()

    pdf_response = client.get(payload["report"]["pdf_url"])
    csv_response = client.get(payload["report"]["csv_url"])

    pdf_text = pdf_response.data.decode("latin-1", errors="ignore")
    csv_text = csv_response.data.decode("utf-8", errors="ignore")

    assert "Fake Probability: " in pdf_text
    assert "Real Probability: " in pdf_text
    assert "Confidence: " in pdf_text
    assert "%" in pdf_text
    assert ".0" not in pdf_text

    assert "fake_probability," in csv_text
    assert "real_probability," in csv_text
    assert "confidence," in csv_text
    assert "%" in csv_text


def test_downloading_legacy_report_converts_float_scores(client, tmp_path):
    reports_dir = Path(client.application.config["REPORTS_DIR"])
    report_id = "legacyreport001"
    pdf_path = reports_dir / f"{report_id}.pdf"
    csv_path = reports_dir / f"{report_id}.csv"

    pdf_path.write_text(
        "\n".join(
            [
                "%PDF-1.4",
                "(Fake Probability: 0.89) Tj",
                "(Real Probability: 0.11) Tj",
                "(Confidence: 0.75) Tj",
            ]
        ),
        encoding="latin-1",
    )
    csv_path.write_text(
        "\n".join(
            [
                "field,value",
                "analysis_id,legacy-analysis",
                "analysis_type,video",
                "status,Fake",
                "fake_probability,0.89",
                "real_probability,0.11",
                "confidence,0.75",
            ]
        ),
        encoding="utf-8",
    )

    store_report_metadata(
        client.application.config["DATABASE_PATH"],
        {
            "id": report_id,
            "analysis_id": "legacy-analysis",
            "report_name": "legacy_video_analysis",
            "analysis_type": "video",
            "pdf_path": str(pdf_path),
            "csv_path": str(csv_path),
            "created_at": "2026-04-01T00:00:00+00:00",
        },
    )

    pdf_response = client.get(f"/api/reports/{report_id}?format=pdf")
    csv_response = client.get(f"/api/reports/{report_id}?format=csv")

    pdf_text = pdf_response.data.decode("latin-1", errors="ignore")
    csv_text = csv_response.data.decode("utf-8", errors="ignore")

    assert "Fake Probability: 89%" in pdf_text
    assert "Real Probability: 11%" in pdf_text
    assert "Confidence: 75%" in pdf_text
    assert "fake_probability,89%" in csv_text
    assert "real_probability,11%" in csv_text
    assert "confidence,75%" in csv_text


def test_news_text_endpoint_returns_prediction_and_report(client):
    response = client.post(
        "/api/news/analyze",
        json={
            "headline": "Viral message claims a secret cure was hidden",
            "body": "The post says everyone must share this hidden truth immediately.",
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["prediction"] in {"FAKE", "REAL"}
    assert "fact_verification" in payload["result"]
    assert "source_credibility" in payload["result"]


def test_news_url_endpoint_supports_mocked_article_extraction(client, monkeypatch):
    import backend.routes.news_routes as news_routes_module

    def fake_analyze_news_url_input(*args, **kwargs):
        return {
            "analysis_type": "news_url",
            "input_name": "example.com",
            "status": "Real",
            "prediction": "REAL",
            "fake_probability": 0.12,
            "real_probability": 0.88,
            "confidence": 0.91,
            "summary": "Mocked URL analysis result.",
            "explanation": ["Trusted source detected."],
            "article": {"domain": "example.com", "title": "Example story"},
            "style_analysis": {"clickbait_score": 0.1, "emotional_tone_score": 0.1, "misleading_language_score": 0.1},
            "model": {"mode": "hybrid-heuristic", "baseline_fake_probability": 0.12, "transformer_used": 0, "transformer_model": "", "transformer_fake_probability": None},
            "source_credibility": {"domain": "example.com", "score": 0.84, "trust_level": "high", "reasons": ["Trusted source detected."]},
            "fact_verification": {"status": "corroborated", "score": 0.82, "reasons": ["Recent coverage supports the claim."], "headlines": []},
            "image_verification": None,
            "metadata": {"source_score": 0.84},
        }

    monkeypatch.setattr(news_routes_module, "analyze_news_url_input", fake_analyze_news_url_input)

    response = client.post("/api/news/analyze-url", json={"url": "https://example.com/story"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["analysis_type"] == "news_url"
    assert payload["result"]["prediction"] == "REAL"


def test_news_image_endpoint_accepts_image_upload(client):
    fake_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRdemo"
    response = client.post(
        "/api/news/analyze-image",
        data={
            "image": (io.BytesIO(fake_png), "sample.png"),
            "caption": "A viral image claims this event happened today.",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["analysis_type"] == "news_image"
    assert payload["result"]["prediction"] in {"FAKE", "REAL"}


def test_video_upload_endpoint(client):
    response = client.post(
        "/api/video/analyze",
        data={"video": (io.BytesIO(b"fake-video-content"), "sample.mp4")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["analysis_type"] == "video"
    assert payload["result"]["prediction"] in {"FAKE", "REAL"}


def test_audio_upload_endpoint_returns_prediction(client):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 3200)
    buffer.seek(0)

    response = client.post(
        "/api/voice/analyze",
        data={"audio": (buffer, "voice.wav")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["prediction"] in {"FAKE", "REAL"}
    assert payload["content_type"] == "audio"
    assert isinstance(payload["reasons"], list)
    assert payload["result"]["analysis_type"] == "audio"
    assert payload["result"]["prediction"] in {"FAKE", "REAL"}


def test_audio_url_endpoint_supports_mocked_analysis(client, monkeypatch):
    import backend.routes.voice_routes as voice_routes_module

    def fake_analyze_voice_url_input(*args, **kwargs):
        return {
            "analysis_type": "audio_url",
            "content_type": "audio",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.88,
            "real_probability": 0.12,
            "confidence": 0.91,
            "summary": "Mocked voice URL analysis result.",
            "reasons": ["Synthetic voice markers detected from the resolved audio link."],
            "explanation": ["Synthetic voice markers detected from the resolved audio link."],
            "model": {"mode": "cnn-lstm-transformer-ensemble", "cnn_ready": 1, "lstm_ready": 1, "transformer_ready": 1},
            "audio_forensics": {
                "feature_extractor": "mocked",
                "suspicious_regions": [],
                "breathing_segments": [],
                "signals": {"breathing_proxy": 0.12, "pitch_consistency_proxy": 0.82},
                "branch_scores": {"cnn": 0.84, "lstm": 0.89, "transformer": 0.83},
            },
            "metadata": {"source_url": "https://example.com/voice.mp3", "sample_rate": 16000},
        }

    monkeypatch.setattr(voice_routes_module, "analyze_voice_url_input", fake_analyze_voice_url_input)

    response = client.post("/api/voice/analyze-url", json={"url": "https://example.com/voice.mp3"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["prediction"] == "FAKE"
    assert payload["result"]["analysis_type"] == "audio_url"


def test_video_url_endpoint_supports_mocked_analysis(client, monkeypatch):
    import backend.routes.video_routes as video_routes_module

    def fake_analyze_video_url_input(*args, **kwargs):
        return {
            "analysis_type": "video_url",
            "content_type": "video",
            "input_name": "https://example.com/video",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.88,
            "real_probability": 0.12,
            "confidence": 0.9,
            "summary": "Mocked video URL analysis result.",
            "reasons": ["Synthetic export markers detected."],
            "explanation": ["Synthetic export markers detected."],
            "source_credibility": {"domain": "example.com", "score": 0.38, "reasons": ["Low trust."]},
            "video_forensics": {
                "frame_sampling_mode": "byte-window-approximation",
                "suspicious_segments": [{"window_index": 1, "estimated_second": 0.7, "anomaly_score": 0.82, "reason": "Abrupt inconsistency."}],
                "signals": {"suspicious_segment_count": 1},
            },
            "metadata": {"resolved_video_url": "https://cdn.example.com/video.mp4", "source_score": 0.38},
        }

    monkeypatch.setattr(video_routes_module, "analyze_video_url_input", fake_analyze_video_url_input)

    response = client.post("/api/video/analyze-url", json={"url": "https://example.com/video"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["analysis_type"] == "video_url"
    assert payload["result"]["prediction"] == "FAKE"


def test_video_url_endpoint_rejects_youtube_link_without_stream_extractor(client, monkeypatch):
    import backend.routes.video_routes as video_routes_module

    def fake_analyze_video_url_input(*args, **kwargs):
        raise ValueError(
            "AI Shield cannot directly analyze YouTube or Shorts links in this runtime because the stream extractor is not installed. "
            "Upload the video file, use a direct MP4 link, or install yt-dlp for streaming URL support."
        )

    monkeypatch.setattr(video_routes_module, "analyze_video_url_input", fake_analyze_video_url_input)

    response = client.post("/api/video/analyze-url", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert response.status_code == 400
    payload = response.get_json()
    assert "yt-dlp" in payload["error"]
    assert "YouTube" in payload["error"] or "Shorts" in payload["error"]


def test_source_only_video_result_stays_real_for_neutral_source():
    from backend.services.video_intelligence_service import _source_only_video_result

    result = _source_only_video_result(
        "https://example.com/watch",
        {
            "score": 0.46,
            "trust_level": "low",
            "risky_match": None,
            "reasons": ["Domain age could not be verified automatically, so age trust signals are limited."],
        },
        {"download_url": None, "mode": "source-only", "page_title": "", "discovery_notes": ["No downloadable video stream was exposed by the submitted page."]},
    )

    assert result["prediction"] == "REAL"
    assert result["fake_probability"] < 0.6


def test_source_only_video_result_can_still_flag_known_risky_source():
    from backend.services.video_intelligence_service import _source_only_video_result

    result = _source_only_video_result(
        "https://risky.example/watch",
        {
            "score": 0.18,
            "trust_level": "low",
            "risky_match": "risky.example",
            "reasons": ["The source matches a high-risk or untrusted domain in the watchlist: risky.example."],
        },
        {"download_url": None, "mode": "source-only", "page_title": "", "discovery_notes": ["No downloadable video stream was exposed by the submitted page."]},
    )

    assert result["prediction"] == "FAKE"
    assert result["fake_probability"] >= 0.6


def test_video_url_service_uses_conservative_threshold_for_limited_embedded_samples(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.62, "risky_match": None, "reasons": ["Trusted source signals are present."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/video.mp4",
            "mode": "embedded",
            "page_title": "Example clip",
            "discovery_notes": ["A playable video URL was discovered from page metadata."],
        },
    )
    monkeypatch.setattr(
        video_service,
        "_download_video",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp4",
            "original_name": "shared_clip.mp4",
            "downloaded_bytes": 1024,
            "truncated": True,
            "content_type": "video/mp4",
        },
    )
    monkeypatch.setattr(
        video_service,
        "analyze_video",
        lambda path, original_name, source_url=None, source_credibility=None: {
            "analysis_type": "video",
            "content_type": "video",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.63,
            "real_probability": 0.37,
            "confidence": 0.92,
            "summary": "Mocked video result.",
            "reasons": ["Temporal inconsistency looked elevated."],
            "explanation": ["Temporal inconsistency looked elevated."],
            "video_forensics": {"signals": {}},
            "metadata": {
                "ai_export_markers": [],
                "generation_marker_score": 0.08,
                "suspicious_window_count": 0,
                "filename_fake_terms": [],
            },
        },
    )

    result = video_service.analyze_video_url_input("https://example.com/watch", uploads_dir="/tmp")
    assert result["video_forensics"]["signals"]["source_only"] == 1
    assert result["prediction"] == "REAL"
    assert result["confidence"] <= 0.57


def test_video_url_service_uses_conservative_threshold_for_neutral_direct_clip(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.58, "risky_match": None, "reasons": ["Neutral source signals are present."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/video.mp4",
            "mode": "direct",
            "page_title": "",
            "discovery_notes": ["The submitted URL points directly to a video resource."],
        },
    )
    monkeypatch.setattr(
        video_service,
        "_download_video",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp4",
            "original_name": "camera_clip.mp4",
            "downloaded_bytes": 1024,
            "truncated": False,
            "content_type": "video/mp4",
            "content_valid": 1,
            "validation_reason": "",
            "head_signature": "ftypmp42",
        },
    )
    monkeypatch.setattr(
        video_service,
        "analyze_video",
        lambda path, original_name, source_url=None, source_credibility=None: {
            "analysis_type": "video",
            "content_type": "video",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.59,
            "real_probability": 0.41,
            "confidence": 0.8,
            "summary": "Mocked video result.",
            "reasons": ["Some weak synthetic-style cues were detected."],
            "explanation": ["Some weak synthetic-style cues were detected."],
            "video_forensics": {"signals": {}},
            "metadata": {
                "ai_export_markers": [],
                "generation_marker_score": 0.12,
                "suspicious_window_count": 1,
                "filename_fake_terms": [],
            },
        },
    )

    result = video_service.analyze_video_url_input("https://example.com/camera.mp4", uploads_dir="/tmp")
    assert result["prediction"] == "FAKE"
    assert result["metadata"]["analysis_filename"] == "url_video_sample.mp4"
    assert result["metadata"]["url_conservative_override"] == 0
    assert result["metadata"]["url_debug"]["download_content_valid"] == 1


def test_video_url_service_preserves_fake_result_for_strong_forensics(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.58, "risky_match": None, "reasons": ["Neutral source signals are present."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/video.mp4",
            "mode": "direct",
            "page_title": "",
            "discovery_notes": ["The submitted URL points directly to a video resource."],
        },
    )
    monkeypatch.setattr(
        video_service,
        "_download_video",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp4",
            "original_name": "camera_clip.mp4",
            "downloaded_bytes": 1024,
            "truncated": False,
            "content_type": "video/mp4",
            "content_valid": 1,
            "validation_reason": "",
            "head_signature": "ftypmp42",
        },
    )
    monkeypatch.setattr(
        video_service,
        "analyze_video",
        lambda path, original_name, source_url=None, source_credibility=None: {
            "analysis_type": "video",
            "content_type": "video",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.88,
            "real_probability": 0.12,
            "confidence": 0.95,
            "summary": "Mocked video result.",
            "reasons": ["Strong synthetic markers were detected."],
            "explanation": ["Strong synthetic markers were detected."],
            "video_forensics": {
                "signals": {
                    "generation_marker_score": 0.52,
                    "suspicious_segment_count": 3,
                    "temporal_consistency_proxy": 0.51,
                    "facial_inconsistency_proxy": 0.42,
                    "lip_sync_proxy": 0.37,
                }
            },
            "metadata": {
                "ai_export_markers": ["facefusion"],
                "generation_marker_score": 0.52,
                "suspicious_window_count": 3,
                "filename_fake_terms": [],
            },
        },
    )

    result = video_service.analyze_video_url_input("https://example.com/camera.mp4", uploads_dir="/tmp")
    assert result["prediction"] == "FAKE"
    assert result["metadata"]["url_conservative_override"] == 0


def test_video_url_service_rejects_invalid_downloaded_html_payload(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.58, "risky_match": None, "reasons": ["Neutral source signals are present."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/video.mp4",
            "mode": "direct",
            "page_title": "",
            "content_type": "video/mp4",
            "discovery_notes": ["The submitted URL points directly to a video resource."],
        },
    )
    monkeypatch.setattr(
        video_service,
        "_download_video",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp4",
            "original_name": "camera_clip.mp4",
            "downloaded_bytes": 2048,
            "truncated": False,
            "content_type": "text/html",
            "content_valid": 0,
            "validation_reason": "The resolved URL returned an HTML page instead of a video file.",
            "head_signature": "<html>",
        },
    )

    with pytest.raises(ValueError, match="HTML page instead of a video file"):
        video_service.analyze_video_url_input("https://example.com/camera.mp4", uploads_dir="/tmp")


def test_video_url_service_uses_ytdlp_download_for_streaming_links(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.setenv("AI_SHIELD_ANALYZE_STREAMING_VIDEO", "true")
    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.52, "risky_match": None, "reasons": ["Neutral source signals are present."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://manifest.googlevideo.com/api/manifest/hls_playlist/index.m3u8",
            "mode": "stream-extracted",
            "page_title": "Example Shorts",
            "content_type": "video/mp4",
            "discovery_notes": ["A streaming-platform URL was resolved to a downloadable video stream using yt-dlp."],
        },
    )

    download_calls = {"requests": 0, "yt_dlp": 0}

    def fake_download_video(*args, **kwargs):
        download_calls["requests"] += 1
        raise AssertionError("Direct requests downloader should not be used for stream-extracted URLs")

    def fake_download_streaming_video_with_yt_dlp(url, uploads_dir, timeout_seconds):
        download_calls["yt_dlp"] += 1
        return {
            "path": "/tmp/mock_stream.mp4",
            "original_name": "shorts_clip.mp4",
            "downloaded_bytes": 8192,
            "truncated": False,
            "content_type": "video/mp4",
            "content_valid": 1,
            "validation_reason": "",
            "head_signature": "ftypisom",
            "download_method": "yt-dlp",
        }

    monkeypatch.setattr(video_service, "_download_video", fake_download_video)
    monkeypatch.setattr(video_service, "_download_streaming_video_with_yt_dlp", fake_download_streaming_video_with_yt_dlp)
    monkeypatch.setattr(
        video_service,
        "analyze_video",
        lambda path, original_name, source_url=None, source_credibility=None: {
            "analysis_type": "video",
            "content_type": "video",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.87,
            "real_probability": 0.13,
            "confidence": 0.92,
            "summary": "Mocked stream analysis result.",
            "reasons": ["Strong synthetic markers were detected."],
            "explanation": ["Strong synthetic markers were detected."],
            "video_forensics": {"signals": {"generation_marker_score": 0.48}},
            "metadata": {
                "sampled_frame_count": 12,
                "has_video_track": 1,
                "has_audio_track": 1,
            },
        },
    )

    result = video_service.analyze_video_url_input("https://youtube.com/shorts/example", uploads_dir="/tmp")
    assert result["prediction"] == "FAKE"
    assert download_calls["yt_dlp"] == 1
    assert download_calls["requests"] == 0
    assert result["metadata"]["download_method"] == "yt-dlp"
    assert result["metadata"]["url_debug"]["download_method"] == "yt-dlp"


def test_video_url_service_uses_fast_source_only_for_streaming_links_by_default(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.delenv("AI_SHIELD_ANALYZE_STREAMING_VIDEO", raising=False)
    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.6, "risky_match": None, "reasons": ["HTTPS is enabled for the submitted source."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://manifest.googlevideo.com/api/manifest/hls_playlist/index.m3u8",
            "mode": "stream-extracted",
            "page_title": "Silenced, not defeated. My message to the aam aadmi",
            "duration_seconds": 138,
            "uploader": "Raghav Chadha Official",
            "content_type": "video/mp4",
            "discovery_notes": ["A streaming-platform URL was resolved to a downloadable video stream using yt-dlp."],
        },
    )

    download_calls = {"yt_dlp": 0, "analysis": 0}

    def fake_download_streaming_video_with_yt_dlp(*args, **kwargs):
        download_calls["yt_dlp"] += 1
        raise AssertionError("Streaming fast mode should not download the full video")

    def fake_analyze_video(*args, **kwargs):
        download_calls["analysis"] += 1
        raise AssertionError("Streaming fast mode should not run frame-level analysis")

    monkeypatch.setattr(video_service, "_download_streaming_video_with_yt_dlp", fake_download_streaming_video_with_yt_dlp)
    monkeypatch.setattr(video_service, "analyze_video", fake_analyze_video)

    result = video_service.analyze_video_url_input("https://youtube.com/shorts/example", uploads_dir="/tmp")
    assert result["prediction"] == "REAL"
    assert result["real_probability"] >= 0.85
    assert result["confidence"] >= 0.85
    assert result["video_forensics"]["signals"]["source_only"] == 1
    assert result["metadata"]["streaming_platform_fast_path"] == 1
    assert result["metadata"]["streaming_real_probability_boost"] == 1
    assert result["metadata"]["source_duration_seconds"] == 138
    assert download_calls == {"yt_dlp": 0, "analysis": 0}


def test_video_url_service_flips_to_fake_for_strong_ai_title_markers(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.55, "risky_match": None, "reasons": ["Neutral source signals are present."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://manifest.googlevideo.com/api/manifest/hls_playlist/index.m3u8",
            "mode": "stream-extracted",
            "page_title": "This Is NOT a Real Person (AI Video by Google's VEO 3) #aivideo #veo3",
            "content_type": "video/mp4",
            "discovery_notes": ["A streaming-platform URL was resolved to a downloadable video stream using yt-dlp."],
        },
    )
    monkeypatch.setattr(
        video_service,
        "_download_streaming_video_with_yt_dlp",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock_stream.mp4",
            "original_name": "shorts_clip.mp4",
            "downloaded_bytes": 8192,
            "truncated": False,
            "content_type": "video/mp4",
            "content_valid": 1,
            "validation_reason": "",
            "head_signature": "ftypisom",
            "download_method": "yt-dlp",
        },
    )
    monkeypatch.setattr(
        video_service,
        "analyze_video",
        lambda path, original_name, source_url=None, source_credibility=None: {
            "analysis_type": "video",
            "content_type": "video",
            "status": "Real",
            "prediction": "REAL",
            "fake_probability": 0.31,
            "real_probability": 0.69,
            "confidence": 0.71,
            "summary": "Mocked stream analysis result.",
            "reasons": ["Frame-level cues were mixed."],
            "explanation": ["Frame-level cues were mixed."],
            "video_forensics": {"signals": {"generation_marker_score": 0.18}},
            "metadata": {
                "sampled_frame_count": 12,
                "has_video_track": 1,
                "has_audio_track": 1,
            },
        },
    )

    result = video_service.analyze_video_url_input("https://youtube.com/shorts/example", uploads_dir="/tmp")
    assert result["prediction"] == "FAKE"
    assert result["fake_probability"] >= 0.68
    assert result["metadata"]["title_fake_signal_score"] >= 0.58
    assert result["metadata"]["title_based_override"] == 1


def test_video_url_service_keeps_low_quality_direct_clip_on_real_side(monkeypatch):
    import backend.services.video_intelligence_service as video_service

    monkeypatch.setattr(
        video_service,
        "_cached_source_credibility",
        lambda url: {"score": 0.57, "risky_match": None, "reasons": ["Neutral source signals are present."]},
    )
    monkeypatch.setattr(
        video_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/video.mp4",
            "mode": "direct",
            "page_title": "Example low quality clip",
            "discovery_notes": ["The submitted URL points directly to a video resource."],
        },
    )
    monkeypatch.setattr(
        video_service,
        "_download_video",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp4",
            "original_name": "camera_clip.mp4",
            "downloaded_bytes": 8192,
            "truncated": False,
            "content_type": "video/mp4",
            "content_valid": 1,
            "validation_reason": "",
            "head_signature": "ftypmp42",
            "download_method": "requests",
        },
    )
    monkeypatch.setattr(
        video_service,
        "analyze_video",
        lambda path, original_name, source_url=None, source_credibility=None: {
            "analysis_type": "video",
            "content_type": "video",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.66,
            "real_probability": 0.34,
            "confidence": 0.9,
            "summary": "Mocked low quality video result.",
            "reasons": ["Compression artifacts looked elevated."],
            "explanation": ["Compression artifacts looked elevated."],
            "video_forensics": {"signals": {"generation_marker_score": 0.08, "visual_artifact_proxy": 0.31}},
            "metadata": {
                "sampled_frame_count": 12,
                "has_video_track": 1,
                "has_audio_track": 1,
                "low_quality_proxy": 0.72,
                "prediction_trace": {
                    "frozen_speech_bundle": 0,
                    "compression_low_quality_relief": 1,
                },
            },
        },
    )

    result = video_service.analyze_video_url_input("https://example.com/low-quality.mp4", uploads_dir="/tmp")
    assert result["prediction"] == "REAL"
    assert result["metadata"]["url_conservative_override"] == 1


def test_audio_url_endpoint_returns_source_only_result_for_youtube_link(client):
    response = client.post("/api/voice/analyze-url", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["result"]["analysis_type"] == "audio_url"
    assert payload["result"]["audio_forensics"]["signals"]["source_only"] == 1
    assert "streaming platform" in " ".join(payload["result"]["reasons"]).lower()


def test_voice_url_service_returns_source_only_result_when_audio_stream_is_unresolved(monkeypatch):
    import backend.services.voice_intelligence_service as voice_service

    monkeypatch.setattr(
        voice_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": None,
            "mode": "unresolved",
            "discovery_notes": ["No downloadable audio stream was exposed by the submitted page."],
        },
    )

    result = voice_service.analyze_voice_url_input("https://example.com/page", uploads_dir="/tmp")
    assert result["analysis_type"] == "audio_url"
    assert result["prediction"] in {"REAL", "FAKE"}
    assert result["audio_forensics"]["signals"]["source_only"] == 1


def test_voice_url_service_uses_conservative_threshold_for_limited_embedded_samples(monkeypatch):
    import backend.services.voice_intelligence_service as voice_service

    monkeypatch.setattr(
        voice_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/voice.mp3",
            "mode": "embedded",
            "discovery_notes": ["A playable audio URL was discovered from page metadata."],
        },
    )
    monkeypatch.setattr(
        voice_service,
        "_download_audio",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp3",
            "original_name": "customer_call_sample.mp3",
            "downloaded_bytes": 1024,
            "truncated": True,
            "content_type": "audio/mpeg",
        },
    )
    monkeypatch.setattr(
        voice_service,
        "analyze_audio",
        lambda path, name: {
            "analysis_type": "audio",
            "content_type": "audio",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.61,
            "real_probability": 0.39,
            "confidence": 0.91,
            "summary": "Mocked voice result.",
            "reasons": ["Pitch looked overly consistent."],
            "explanation": ["Pitch looked overly consistent."],
            "metadata": {},
        },
    )

    result = voice_service.analyze_voice_url_input("https://example.com/page", uploads_dir="/tmp")
    assert result["audio_forensics"]["signals"]["source_only"] == 1
    assert result["prediction"] == "REAL"
    assert result["confidence"] <= 0.55


def test_voice_url_service_preserves_fake_result_for_strong_synthetic_source_name(monkeypatch):
    import backend.services.voice_intelligence_service as voice_service

    monkeypatch.setattr(
        voice_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/voice.mp3",
            "mode": "embedded",
            "discovery_notes": ["A playable audio URL was discovered from page metadata."],
        },
    )
    monkeypatch.setattr(
        voice_service,
        "_download_audio",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp3",
            "original_name": "elevenlabs_voice_clone.mp3",
            "downloaded_bytes": 1024,
            "truncated": False,
            "content_type": "audio/mpeg",
            "content_valid": 1,
            "validation_reason": "",
            "head_signature": "ID3",
        },
    )
    monkeypatch.setattr(
        voice_service,
        "analyze_audio",
        lambda path, name: {
            "analysis_type": "audio",
            "content_type": "audio",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.88,
            "real_probability": 0.12,
            "confidence": 0.95,
            "summary": "Mocked voice result.",
            "reasons": ["Strong synthetic markers detected."],
            "explanation": ["Strong synthetic markers detected."],
            "metadata": {},
        },
    )

    result = voice_service.analyze_voice_url_input("https://example.com/page", uploads_dir="/tmp")
    assert result["prediction"] == "FAKE"
    assert result["fake_probability"] >= 0.8


def test_voice_url_service_uses_conservative_threshold_for_weak_fake_signal_even_when_not_limited(monkeypatch):
    import backend.services.voice_intelligence_service as voice_service

    monkeypatch.setattr(
        voice_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/voice.mp3",
            "mode": "direct",
            "discovery_notes": ["The submitted URL points directly to an audio resource."],
        },
    )
    monkeypatch.setattr(
        voice_service,
        "_download_audio",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp3",
            "original_name": "customer_call_sample.mp3",
            "downloaded_bytes": 1024,
            "truncated": False,
            "content_type": "audio/mpeg",
            "content_valid": 1,
            "validation_reason": "",
            "head_signature": "ID3",
        },
    )
    monkeypatch.setattr(
        voice_service,
        "analyze_audio",
        lambda path, name: {
            "analysis_type": "audio",
            "content_type": "audio",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.61,
            "real_probability": 0.39,
            "confidence": 0.82,
            "summary": "Mocked voice result.",
            "reasons": ["A few synthetic-style cues were detected."],
            "explanation": ["A few synthetic-style cues were detected."],
            "metadata": {},
        },
    )

    result = voice_service.analyze_voice_url_input("https://example.com/direct.mp3", uploads_dir="/tmp")
    assert result["prediction"] == "FAKE"
    assert result["metadata"]["analysis_filename"] == "url_audio_sample.mp3"
    assert result["metadata"]["url_conservative_override"] == 0
    assert result["metadata"]["url_debug"]["download_content_valid"] == 1


def test_voice_url_service_rejects_invalid_downloaded_html_payload(monkeypatch):
    import backend.services.voice_intelligence_service as voice_service

    monkeypatch.setattr(
        voice_service,
        "_cached_discovery",
        lambda url, timeout: {
            "download_url": "https://cdn.example.com/voice.mp3",
            "mode": "direct",
            "discovery_notes": ["The submitted URL points directly to an audio resource."],
        },
    )
    monkeypatch.setattr(
        voice_service,
        "_download_audio",
        lambda url, uploads_dir, timeout_seconds: {
            "path": "/tmp/mock.mp3",
            "original_name": "customer_call_sample.mp3",
            "downloaded_bytes": 1024,
            "truncated": False,
            "content_type": "text/html",
            "content_valid": 0,
            "validation_reason": "The resolved URL returned an HTML page instead of an audio file.",
            "head_signature": "<html>",
        },
    )

    with pytest.raises(ValueError, match="HTML page instead of an audio file"):
        voice_service.analyze_voice_url_input("https://example.com/direct.mp3", uploads_dir="/tmp")


def test_news_url_service_stays_real_for_neutral_source_when_article_extraction_fails(monkeypatch):
    import backend.services.news_intelligence_service as news_service

    monkeypatch.setattr(
        news_service,
        "_cached_article_result",
        lambda url, timeout: {
            "success": False,
            "domain": "example.com",
            "url": url,
            "resolved_url": url,
            "title": "",
            "body": "",
        },
    )
    monkeypatch.setattr(
        news_service,
        "_cached_source_result",
        lambda url: {
            "domain": "example.com",
            "score": 0.48,
            "trust_level": "low",
            "risky_match": None,
            "reasons": ["Domain age could not be verified automatically, so age trust signals are limited."],
        },
    )

    result = news_service.analyze_news_url_input("https://example.com/story")
    assert result["prediction"] == "REAL"
    assert result["fake_probability"] < 0.6


def test_news_url_service_can_flag_known_risky_source_when_article_extraction_fails(monkeypatch):
    import backend.services.news_intelligence_service as news_service

    monkeypatch.setattr(
        news_service,
        "_cached_article_result",
        lambda url, timeout: {
            "success": False,
            "domain": "risky.example",
            "url": url,
            "resolved_url": url,
            "title": "",
            "body": "",
        },
    )
    monkeypatch.setattr(
        news_service,
        "_cached_source_result",
        lambda url: {
            "domain": "risky.example",
            "score": 0.18,
            "trust_level": "low",
            "risky_match": "risky.example",
            "reasons": ["The source matches a high-risk or untrusted domain in the watchlist: risky.example."],
        },
    )

    result = news_service.analyze_news_url_input("https://risky.example/story")
    assert result["prediction"] == "FAKE"
    assert result["fake_probability"] >= 0.6


def test_news_url_service_uses_conservative_threshold_for_neutral_extracted_articles(monkeypatch):
    import backend.services.news_intelligence_service as news_service

    monkeypatch.setattr(
        news_service,
        "_cached_article_result",
        lambda url, timeout: {
            "success": True,
            "domain": "example.com",
            "url": url,
            "resolved_url": url,
            "title": "Community update",
            "body": "A local organization shared a routine update with no strong evidence of misinformation.",
        },
    )
    monkeypatch.setattr(
        news_service,
        "_cached_source_result",
        lambda url: {
            "domain": "example.com",
            "score": 0.64,
            "trust_level": "medium",
            "risky_match": None,
            "reasons": ["Trusted source signals are present."],
        },
    )
    monkeypatch.setattr(
        news_service,
        "analyze_news_text_input",
        lambda *args, **kwargs: {
            "analysis_type": "news_text",
            "input_name": "Community update",
            "status": "Fake",
            "prediction": "FAKE",
            "fake_probability": 0.59,
            "real_probability": 0.41,
            "confidence": 0.8,
            "summary": "Mocked news result.",
            "explanation": ["Only weak misinformation cues were detected."],
            "article": {"headline": "Community update", "body": "Routine update", "language": "en"},
            "style_analysis": {"clickbait_score": 0.12, "emotional_tone_score": 0.08, "misleading_language_score": 0.1},
            "model": {"mode": "mock"},
            "fact_verification": {"status": "partial", "score": 0.42, "reasons": [], "headlines": []},
            "metadata": {},
        },
    )

    result = news_service.analyze_news_url_input("https://example.com/story")
    assert result["prediction"] == "FAKE"
    assert result["fake_probability"] == 0.59
    assert result["metadata"]["url_conservative_override"] == 0
    assert result["metadata"]["url_debug"]["article_extraction_success"] == 1


def test_feedback_submission(client):
    response = client.post(
        "/api/feedback/submit",
        json={
            "name": "Tester",
            "email": "tester@example.com",
            "category": "general",
            "rating": 5,
            "message": "The workflow is clear.",
        },
    )
    assert response.status_code == 201
    assert response.get_json()["feedback"]["name"] == "Tester"


def test_chat_endpoint_returns_language_reply_and_tts(client):
    response = client.post(
        "/chat",
        json={
            "message": "Explain the confidence score",
            "language": "en",
            "session_id": "test-session",
            "context": {"current_page": "/dashboard.html"},
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["language"] == "en"
    assert "confidence" in payload["reply"].lower()
    assert payload["tts"]["lang"] == "en-US"


def test_chat_endpoint_returns_hindi_reply_for_hindi_message(client):
    response = client.post(
        "/chat",
        json={
            "message": "मुझे रिपोर्ट डाउनलोड करनी है",
            "language": "auto",
            "session_id": "hindi-session",
            "context": {"current_page": "/history.html"},
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["language"] == "hi"
    assert payload["tts"]["lang"] == "hi-IN"
    assert "रिपोर्ट" in payload["reply"]


def test_chat_endpoint_uses_session_memory_for_follow_up(client):
    first_response = client.post(
        "/chat",
        json={
            "message": "Explain voice detection",
            "language": "en",
            "session_id": "memory-session",
            "context": {"current_page": "/upload.html"},
        },
    )
    assert first_response.status_code == 200

    follow_up_response = client.post(
        "/chat",
        json={
            "message": "and how does it work?",
            "language": "en",
            "session_id": "memory-session",
            "context": {"current_page": "/upload.html"},
        },
    )
    assert follow_up_response.status_code == 200
    payload = follow_up_response.get_json()
    assert "audio" in payload["reply"].lower() or "voice" in payload["reply"].lower()


def test_dashboard_summary_returns_total_counts_and_recent_limit(client):
    first_response = client.post(
        "/api/news/analyze",
        json={"body": "Fake miracle cure claim spreads very quickly online."},
    )
    second_response = client.post(
        "/api/news/analyze",
        json={"body": "Official bulletin confirms a verified public announcement."},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    response = client.get("/api/dashboard/summary?limit=1")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["stats"]["total_analyses"] == 2
    assert payload["stats"]["report_count"] == 2
    assert len(payload["recent"]) == 1


def test_chat_endpoint_can_summarize_recent_history_from_backend_context(client):
    client.post(
        "/api/news/analyze",
        json={"body": "Breaking! This unbelievable miracle cure was exposed by a secret source!!!"},
    )
    client.post(
        "/api/news/analyze",
        json={"body": "Official report cites verified data and evidence from multiple agencies."},
    )

    response = client.post(
        "/chat",
        json={
            "message": "show my recent history",
            "language": "en",
            "session_id": "history-session",
            "context": {"current_page": "/history.html"},
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert "recent analysis history" in payload["reply"].lower()


def test_chat_endpoint_prioritizes_latest_result_explanation_over_history_keyword(client):
    analysis_response = client.post(
        "/api/news/analyze",
        json={"body": "The Government of India released an official press note about the new public health scheme."},
    )
    assert analysis_response.status_code == 200
    latest_result = analysis_response.get_json()["result"]

    response = client.post(
        "/chat",
        json={
            "message": "Explain the latest result in detail",
            "language": "en",
            "session_id": "latest-result-session",
            "context": {
                "current_page": "/dashboard.html",
                "latest_result": latest_result,
            },
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert "status:" in payload["reply"].lower()
    assert "confidence" in payload["reply"].lower()
