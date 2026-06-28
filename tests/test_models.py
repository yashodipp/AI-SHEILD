from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.models.deepfake_video_model import analyze_video
from backend.models.fake_news_model import analyze_news
from backend.models.fake_voice_model import analyze_audio
from backend.services.news_intelligence_service import analyze_news_text_input


def _write_float_wave(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    clipped = np.clip(samples, -1, 1)
    pcm = (clipped * 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def test_fake_news_heuristic_scores_sensational_text_higher():
    suspicious = analyze_news("SHOCKING viral miracle exposed by secret source!!!")
    credible = analyze_news("Official report includes verified data, evidence, and source links.")
    assert suspicious["fake_probability"] > credible["fake_probability"]
    assert suspicious["status"] == "Fake"
    assert credible["status"] == "Real"


def test_fake_news_flags_clickbait_hidden_truth_as_fake():
    result = analyze_news("You will not believe this hidden truth the media does not want you to know!")
    assert result["status"] == "Fake"


def test_fake_news_marks_peer_reviewed_report_as_real():
    result = analyze_news("Scientists published a peer-reviewed study with methods and evidence.")
    assert result["status"] == "Real"


def test_fake_news_flags_whatsapp_forward_without_official_notice_as_fake():
    result = analyze_news("A WhatsApp forward claims that banks will shut down tomorrow, but provides no official notice.")
    assert result["status"] == "Fake"


def test_fake_news_gives_high_real_probability_to_financial_statement():
    result = analyze_news("The company reported quarterly revenue in its published financial statement.")
    assert result["status"] == "Real"
    assert result["real_probability"] >= 0.9


def test_fake_news_flags_hindi_viral_bank_shutdown_claim_as_fake():
    result = analyze_news("सोशल मीडिया पर दावा किया जा रहा है कि भारत में अगले हफ्ते सभी बैंक अचानक बंद होने वाले हैं।")
    assert result["status"] == "Fake"


def test_fake_news_marks_hindi_official_policy_update_as_real():
    result = analyze_news("भारत सरकार ने नई स्वास्थ्य योजना से जुड़ा आधिकारिक प्रेस नोट जारी किया।")
    assert result["status"] == "Real"
    assert result["real_probability"] >= 0.9


def test_fake_news_live_context_reduces_fake_probability_for_supported_real_claim():
    text = "Health officials announced a new public health scheme for rural districts."
    baseline = analyze_news(text)
    boosted = analyze_news(
        text,
        live_context={
            "used": True,
            "article_count": 6,
            "supporting_article_count": 4,
            "supporting_sources": ["Source A", "Source B", "Source C"],
            "corroboration_score": 0.72,
            "fact_check_score": 0.0,
            "provider": "google_news_rss",
            "latest_headlines": [{"title": "Health ministry launches rural scheme", "source": "Source A"}],
        },
    )
    assert boosted["fake_probability"] < baseline["fake_probability"]
    assert boosted["metadata"]["live_lookup_used"] == 1
    assert boosted["metadata"]["live_provider"] == "google_news_rss"


def test_fake_news_live_context_increases_fake_probability_for_fact_checked_claim():
    text = "A viral post says the election results were secretly changed."
    baseline = analyze_news(text)
    boosted = analyze_news(
        text,
        live_context={
            "used": True,
            "article_count": 4,
            "supporting_article_count": 1,
            "supporting_sources": ["Fact Check Source"],
            "corroboration_score": 0.1,
            "fact_check_score": 0.5,
        },
    )
    assert boosted["fake_probability"] > baseline["fake_probability"]


def test_video_model_returns_expected_shape(tmp_path):
    sample_video = tmp_path / "clip.mp4"
    sample_video.write_bytes(b"\x00\x00\x00\x18ftypmp42demo-video")
    result = analyze_video(str(sample_video), sample_video.name)
    assert result["analysis_type"] == "video"
    assert result["content_type"] == "video"
    assert result["prediction"] in {"FAKE", "REAL"}
    assert "model" in result
    assert "video_forensics" in result
    assert 0 <= result["fake_probability"] <= 1


def test_video_model_flags_obvious_fake_filename(tmp_path):
    sample_video = tmp_path / "deepfake_generated_clip.mp4"
    sample_video.write_bytes(b"\x00\x00\x00\x18ftypmp42demo-video")
    result = analyze_video(str(sample_video), sample_video.name)
    assert result["status"] == "Fake"
    assert result["confidence"] >= 0.9


def test_video_model_uses_original_name_even_if_stored_name_is_generic(tmp_path):
    sample_video = tmp_path / "e1f23ab4.mp4"
    sample_video.write_bytes(b"\x00\x00\x00\x18ftypmp42demo-video")
    result = analyze_video(str(sample_video), "deepfake_generated_clip.mp4")
    assert result["status"] == "Fake"


def test_video_model_exposes_suspicious_segment_list(tmp_path):
    sample_video = tmp_path / "generated_clip.mp4"
    sample_video.write_bytes((b"\x00\x00\x00\x18ftypmp42" + b"Generated" * 900)[:12000])
    result = analyze_video(str(sample_video), "generated_clip.mp4")
    assert "suspicious_segments" in result["video_forensics"]
    assert isinstance(result["video_forensics"]["suspicious_segments"], list)


def test_video_model_is_more_conservative_for_structured_mp4(tmp_path):
    sample_video = tmp_path / "family_trip.mp4"
    mp4_like = (
        b"\x00\x00\x00\x18ftypmp42"
        + b"\x00\x00\x00\x20moovmvhdtrakmdiastbl"
        + b"\x00\x00\x00\x20mdatvideavc1sounmp4a"
        + (b"\x11\x22\x33\x44\x55\x66\x77\x88" * 1500)
    )
    sample_video.write_bytes(mp4_like)

    result = analyze_video(str(sample_video), sample_video.name)
    assert result["prediction"] == "REAL"


def test_video_model_keeps_compressed_mobile_mp4_on_real_side(monkeypatch):
    import backend.models.deepfake_video_model as video_model_module

    monkeypatch.setattr(
        video_model_module,
        "extract_video_features",
        lambda _: {
            "filename_fake_terms": [],
            "filename_real_terms": [],
            "has_video_track": 1,
            "moov_present": 1,
            "mdat_present": 1,
            "frame_sampling_mode": "opencv-frame-sampling",
            "has_whatsapp_marker": 1,
            "size_mb": 1.68,
            "extension": "mp4",
            "entropy_hint": 0.66,
            "unique_byte_ratio": 1.0,
            "repeated_byte_ratio": 0.984,
            "header_signature": "ftypmp42",
            "generation_marker_score": 0.0,
            "temporal_consistency_proxy": 0.41,
            "lighting_mismatch_proxy": 0.24,
            "audio_video_sync_proxy": 0.05,
            "facial_inconsistency_proxy": 0.32,
            "lip_sync_proxy": 0.18,
            "visual_artifact_proxy": 0.12,
            "face_presence_ratio": 0.92,
            "no_face_frame_ratio": 0.08,
            "mean_sharpness": 22.0,
            "low_sharpness_frame_ratio": 0.18,
            "mean_mouth_motion": 0.031,
            "low_quality_proxy": 0.28,
            "frozen_speech_proxy": 0.0,
            "suspicious_frame_count": 0,
            "suspicious_frame_score_mean": 0.0,
            "suspicious_window_count": 0,
            "has_audio_track": 1,
            "ai_export_markers": [],
            "duration_seconds": 11.12,
            "bitrate_kbps": 1268.6,
            "has_beam_atom": 1,
            "compression_distribution_context": 1,
            "suspicious_segments": [],
        },
    )

    result = video_model_module.analyze_video("/tmp/dummy.mp4", "camera_capture_clip.mp4")
    assert result["prediction"] == "REAL"
    assert result["confidence"] >= 0.9


def test_video_model_flags_frozen_speech_talking_face_pattern_as_fake(monkeypatch):
    import backend.models.deepfake_video_model as video_model_module

    monkeypatch.setattr(
        video_model_module,
        "extract_video_features",
        lambda _: {
            "filename_fake_terms": [],
            "filename_real_terms": [],
            "has_video_track": 1,
            "moov_present": 1,
            "mdat_present": 1,
            "frame_sampling_mode": "opencv-frame-sampling",
            "has_whatsapp_marker": 1,
            "size_mb": 1.68,
            "extension": "mp4",
            "entropy_hint": 0.66,
            "unique_byte_ratio": 1.0,
            "repeated_byte_ratio": 0.984,
            "header_signature": "ftypmp42",
            "generation_marker_score": 0.0,
            "temporal_consistency_proxy": 0.41,
            "lighting_mismatch_proxy": 0.24,
            "audio_video_sync_proxy": 0.05,
            "facial_inconsistency_proxy": 0.32,
            "lip_sync_proxy": 0.18,
            "visual_artifact_proxy": 0.2,
            "face_presence_ratio": 1.0,
            "no_face_frame_ratio": 0.0,
            "mean_sharpness": 18.0,
            "low_sharpness_frame_ratio": 0.22,
            "mean_mouth_motion": 0.0,
            "low_quality_proxy": 0.34,
            "frozen_speech_proxy": 0.69,
            "suspicious_frame_count": 0,
            "suspicious_frame_score_mean": 0.0,
            "suspicious_window_count": 0,
            "has_audio_track": 1,
            "ai_export_markers": [],
            "duration_seconds": 11.12,
            "bitrate_kbps": 1268.6,
            "has_beam_atom": 1,
            "compression_distribution_context": 1,
            "suspicious_segments": [],
        },
    )

    result = video_model_module.analyze_video("/tmp/dummy.mp4", "WhatsApp_Video_2026-03-27_at_21.49.18.mp4")
    assert result["prediction"] == "FAKE"
    assert result["confidence"] >= 0.9


def test_video_model_keeps_frozen_speech_without_other_anomalies_on_real_side(monkeypatch):
    import backend.models.deepfake_video_model as video_model_module

    monkeypatch.setattr(
        video_model_module,
        "extract_video_features",
        lambda _: {
            "filename_fake_terms": [],
            "filename_real_terms": [],
            "has_video_track": 1,
            "moov_present": 1,
            "mdat_present": 1,
            "frame_sampling_mode": "opencv-frame-sampling",
            "has_whatsapp_marker": 1,
            "size_mb": 5.22,
            "extension": "mp4",
            "entropy_hint": 0.67,
            "unique_byte_ratio": 1.0,
            "repeated_byte_ratio": 0.9,
            "header_signature": "ftypmp42",
            "generation_marker_score": 0.0,
            "temporal_consistency_proxy": 0.39,
            "lighting_mismatch_proxy": 0.23,
            "audio_video_sync_proxy": 0.05,
            "facial_inconsistency_proxy": 0.0,
            "lip_sync_proxy": 0.18,
            "visual_artifact_proxy": 0.15,
            "face_presence_ratio": 1.0,
            "no_face_frame_ratio": 0.0,
            "mean_sharpness": 20.0,
            "low_sharpness_frame_ratio": 0.12,
            "mean_mouth_motion": 0.0,
            "low_quality_proxy": 0.31,
            "frozen_speech_proxy": 0.69,
            "suspicious_frame_count": 0,
            "suspicious_frame_score_mean": 0.0,
            "suspicious_window_count": 0,
            "has_audio_track": 1,
            "ai_export_markers": [],
            "duration_seconds": 8.43,
            "bitrate_kbps": 1844.0,
            "has_beam_atom": 1,
            "compression_distribution_context": 1,
            "suspicious_segments": [],
        },
    )

    result = video_model_module.analyze_video("/tmp/dummy.mp4", "WhatsApp_Video_real_case.mp4")
    assert result["prediction"] == "REAL"


def test_video_model_flags_structured_mp4_with_strong_forensics_as_fake(monkeypatch):
    import backend.models.deepfake_video_model as video_model_module

    monkeypatch.setattr(
        video_model_module,
        "extract_video_features",
        lambda _: {
            "filename_fake_terms": [],
            "filename_real_terms": [],
            "has_video_track": 1,
            "moov_present": 1,
            "mdat_present": 1,
            "frame_sampling_mode": "opencv-frame-sampling",
            "has_whatsapp_marker": 0,
            "size_mb": 6.2,
            "extension": "mp4",
            "entropy_hint": 0.71,
            "unique_byte_ratio": 0.93,
            "repeated_byte_ratio": 0.71,
            "header_signature": "ftypmp42",
            "generation_marker_score": 0.44,
            "temporal_consistency_proxy": 0.58,
            "lighting_mismatch_proxy": 0.37,
            "audio_video_sync_proxy": 0.22,
            "facial_inconsistency_proxy": 0.49,
            "lip_sync_proxy": 0.42,
            "visual_artifact_proxy": 0.53,
            "face_presence_ratio": 0.67,
            "no_face_frame_ratio": 0.33,
            "mean_sharpness": 28.0,
            "low_sharpness_frame_ratio": 0.05,
            "mean_mouth_motion": 0.009,
            "low_quality_proxy": 0.1,
            "suspicious_frame_count": 3,
            "suspicious_frame_score_mean": 0.51,
            "suspicious_window_count": 3,
            "has_audio_track": 1,
            "ai_export_markers": ["Synthesia"],
            "duration_seconds": 9.12,
            "bitrate_kbps": 1660.2,
            "has_beam_atom": 0,
            "compression_distribution_context": 0,
            "suspicious_segments": [
                {"estimated_second": 1.4, "anomaly_score": 0.62, "reason": "Face geometry shifts abruptly."},
                {"estimated_second": 4.8, "anomaly_score": 0.58, "reason": "Mouth movement stays unusually static."},
            ],
        },
    )

    result = video_model_module.analyze_video("/tmp/dummy.mp4", "conference_clip.mp4")
    assert result["prediction"] == "FAKE"
    assert result["confidence"] >= 0.9


def test_video_model_flags_moderate_visual_and_temporal_bundle_as_fake(monkeypatch):
    import backend.models.deepfake_video_model as video_model_module

    monkeypatch.setattr(
        video_model_module,
        "extract_video_features",
        lambda _: {
            "filename_fake_terms": [],
            "filename_real_terms": [],
            "has_video_track": 1,
            "moov_present": 1,
            "mdat_present": 1,
            "frame_sampling_mode": "opencv-frame-sampling",
            "has_whatsapp_marker": 1,
            "size_mb": 1.8,
            "extension": "mp4",
            "entropy_hint": 0.63,
            "unique_byte_ratio": 0.92,
            "repeated_byte_ratio": 0.82,
            "header_signature": "ftypmp42",
            "generation_marker_score": 0.0,
            "temporal_consistency_proxy": 0.57,
            "lighting_mismatch_proxy": 0.22,
            "audio_video_sync_proxy": 0.05,
            "facial_inconsistency_proxy": 0.5,
            "lip_sync_proxy": 0.18,
            "visual_artifact_proxy": 0.56,
            "face_presence_ratio": 0.52,
            "no_face_frame_ratio": 0.48,
            "mean_sharpness": 17.0,
            "low_sharpness_frame_ratio": 0.3,
            "mean_mouth_motion": 0.014,
            "low_quality_proxy": 0.44,
            "suspicious_frame_count": 2,
            "suspicious_frame_score_mean": 0.49,
            "suspicious_window_count": 0,
            "has_audio_track": 1,
            "ai_export_markers": [],
            "duration_seconds": 10.4,
            "bitrate_kbps": 1320.0,
            "has_beam_atom": 1,
            "compression_distribution_context": 1,
            "suspicious_segments": [
                {"estimated_second": 2.1, "anomaly_score": 0.51, "reason": "Face region shifts abruptly."},
                {"estimated_second": 5.4, "anomaly_score": 0.48, "reason": "Frame-level anomaly threshold crossed."},
            ],
        },
    )

    result = video_model_module.analyze_video("/tmp/dummy.mp4", "WhatsApp_Video_fake_case.mp4")
    assert result["prediction"] == "FAKE"


def test_video_model_keeps_low_quality_compressed_real_clip_on_real_side(monkeypatch):
    import backend.models.deepfake_video_model as video_model_module

    monkeypatch.setattr(
        video_model_module,
        "extract_video_features",
        lambda _: {
            "filename_fake_terms": [],
            "filename_real_terms": [],
            "has_video_track": 1,
            "moov_present": 1,
            "mdat_present": 1,
            "frame_sampling_mode": "opencv-frame-sampling",
            "has_whatsapp_marker": 1,
            "size_mb": 1.12,
            "extension": "mp4",
            "entropy_hint": 0.61,
            "unique_byte_ratio": 0.96,
            "repeated_byte_ratio": 0.9,
            "header_signature": "ftypmp42",
            "generation_marker_score": 0.0,
            "temporal_consistency_proxy": 0.46,
            "lighting_mismatch_proxy": 0.29,
            "audio_video_sync_proxy": 0.07,
            "facial_inconsistency_proxy": 0.34,
            "lip_sync_proxy": 0.16,
            "visual_artifact_proxy": 0.31,
            "face_presence_ratio": 0.88,
            "no_face_frame_ratio": 0.12,
            "mean_sharpness": 10.4,
            "low_sharpness_frame_ratio": 0.74,
            "mean_mouth_motion": 0.027,
            "low_quality_proxy": 0.72,
            "frozen_speech_proxy": 0.0,
            "suspicious_frame_count": 1,
            "suspicious_frame_score_mean": 0.24,
            "suspicious_window_count": 0,
            "has_audio_track": 1,
            "ai_export_markers": [],
            "duration_seconds": 10.2,
            "bitrate_kbps": 612.0,
            "has_beam_atom": 1,
            "compression_distribution_context": 1,
            "suspicious_segments": [],
        },
    )

    result = video_model_module.analyze_video("/tmp/dummy.mp4", "WhatsApp_low_quality_real.mp4")
    assert result["prediction"] == "REAL"
    assert result["metadata"]["prediction_trace"]["compression_low_quality_relief"] == 1


def test_video_model_preserves_fake_for_low_quality_clip_with_strong_fake_markers(monkeypatch):
    import backend.models.deepfake_video_model as video_model_module

    monkeypatch.setattr(
        video_model_module,
        "extract_video_features",
        lambda _: {
            "filename_fake_terms": [],
            "filename_real_terms": [],
            "has_video_track": 1,
            "moov_present": 1,
            "mdat_present": 1,
            "frame_sampling_mode": "opencv-frame-sampling",
            "has_whatsapp_marker": 1,
            "size_mb": 1.18,
            "extension": "mp4",
            "entropy_hint": 0.62,
            "unique_byte_ratio": 0.94,
            "repeated_byte_ratio": 0.88,
            "header_signature": "ftypmp42",
            "generation_marker_score": 0.26,
            "temporal_consistency_proxy": 0.57,
            "lighting_mismatch_proxy": 0.33,
            "audio_video_sync_proxy": 0.08,
            "facial_inconsistency_proxy": 0.43,
            "lip_sync_proxy": 0.28,
            "visual_artifact_proxy": 0.49,
            "face_presence_ratio": 0.86,
            "no_face_frame_ratio": 0.14,
            "mean_sharpness": 10.0,
            "low_sharpness_frame_ratio": 0.78,
            "mean_mouth_motion": 0.008,
            "low_quality_proxy": 0.76,
            "frozen_speech_proxy": 0.63,
            "suspicious_frame_count": 2,
            "suspicious_frame_score_mean": 0.41,
            "suspicious_window_count": 2,
            "has_audio_track": 1,
            "ai_export_markers": ["HeyGen"],
            "duration_seconds": 9.6,
            "bitrate_kbps": 590.0,
            "has_beam_atom": 1,
            "compression_distribution_context": 1,
            "suspicious_segments": [
                {"estimated_second": 2.3, "anomaly_score": 0.58, "reason": "Face region shifts abruptly."},
            ],
        },
    )

    result = video_model_module.analyze_video("/tmp/dummy.mp4", "WhatsApp_low_quality_fake.mp4")
    assert result["prediction"] == "FAKE"


def test_video_model_exposes_prediction_trace(tmp_path):
    sample_video = tmp_path / "clip.mp4"
    sample_video.write_bytes(b"\x00\x00\x00\x18ftypmp42demo-video")
    result = analyze_video(str(sample_video), sample_video.name)
    prediction_trace = result["metadata"]["prediction_trace"]
    assert "artifact_branch" in prediction_trace
    assert "temporal_branch" in prediction_trace
    assert "decision_threshold" in prediction_trace


def test_audio_model_returns_expected_shape(tmp_path):
    sample_audio = tmp_path / "voice.wav"
    with wave.open(str(sample_audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)

    result = analyze_audio(str(sample_audio), sample_audio.name)
    assert result["analysis_type"] == "audio"
    assert result["content_type"] == "audio"
    assert result["prediction"] in {"FAKE", "REAL"}
    assert "audio_forensics" in result
    assert result["metadata"]["sample_rate"] == 16000
    assert result["model"]["mode"] == "cnn-lstm-transformer-ensemble"


def test_audio_model_flags_obvious_synthetic_clip(tmp_path):
    sample_audio = tmp_path / "ai_voice_clone.wav"
    with wave.open(str(sample_audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes((b"\x10\x00" * 24000))

    result = analyze_audio(str(sample_audio), sample_audio.name)
    assert result["status"] == "Fake"


def test_audio_model_includes_explainable_reasons_and_regions(tmp_path):
    sample_audio = tmp_path / "synthetic.wav"
    with wave.open(str(sample_audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes((b"\x20\x00" * 32000))

    result = analyze_audio(str(sample_audio), sample_audio.name)
    assert isinstance(result["reasons"], list)
    assert isinstance(result["audio_forensics"]["suspicious_regions"], list)


def test_audio_model_uses_original_name_even_if_stored_name_is_generic(tmp_path):
    sample_audio = tmp_path / "e1f23ab4.wav"
    with wave.open(str(sample_audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes((b"\x10\x00" * 24000))

    result = analyze_audio(str(sample_audio), "ai_voice_clone.wav")
    assert result["status"] == "Fake"


def test_audio_model_keeps_human_like_variable_speech_on_real_side(tmp_path):
    sample_audio = tmp_path / "human_like.wav"
    sample_rate = 16000
    parts = []
    for index in range(6):
        duration = 0.55
        timeline = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        frequency = 165 + index * 12 + 8 * np.sin(2 * np.pi * 1.7 * timeline)
        tone = 0.24 * np.sin(2 * np.pi * frequency * timeline) * (0.7 + 0.3 * np.sin(2 * np.pi * 3 * timeline))
        noise = np.random.default_rng(42 + index).normal(0, 0.008, tone.shape)
        parts.append(tone + noise)
        parts.append(np.zeros(int(sample_rate * (0.07 + (index % 3) * 0.02))))
    _write_float_wave(sample_audio, np.concatenate(parts), sample_rate)

    result = analyze_audio(str(sample_audio), sample_audio.name)
    assert result["prediction"] == "REAL"


def test_audio_model_flags_flat_monotone_tone_as_fake(tmp_path):
    sample_audio = tmp_path / "synthetic_like.wav"
    sample_rate = 16000
    timeline = np.linspace(0, 6, int(sample_rate * 6), endpoint=False)
    synthetic = 0.22 * np.sin(2 * np.pi * 220 * timeline)
    _write_float_wave(sample_audio, synthetic, sample_rate)

    result = analyze_audio(str(sample_audio), sample_audio.name)
    assert result["prediction"] == "FAKE"


def test_audio_model_flags_bundled_synthetic_sample_as_fake():
    bundled_sample = PROJECT_ROOT / "dataset" / "voice_samples" / "synthetic_style.wav"
    result = analyze_audio(str(bundled_sample), bundled_sample.name)
    assert result["prediction"] == "FAKE"


def test_audio_model_flags_uploaded_ai_voice_generator_sample_as_fake():
    sample = PROJECT_ROOT / "backend" / "runtime" / "uploads" / "audio" / "9dc1bea852cf494e8a94303a197591ee_AIVoiceGenerator_com_27-03-2026T22_15_24__Matthew.mp3"
    result = analyze_audio(str(sample), sample.name)
    assert result["prediction"] == "FAKE"
    assert result["confidence"] >= 0.9


def test_audio_model_flags_uploaded_voicemaker_sample_as_fake():
    sample = PROJECT_ROOT / "backend" / "runtime" / "uploads" / "audio" / "18e4a369969a4a2eba4bacb9f27d427b_1774628603922228640euum2mf-voicemaker.in-speech.mp3"
    result = analyze_audio(str(sample), sample.name)
    assert result["prediction"] == "FAKE"


def test_audio_model_reports_high_confidence_for_standard_real_recording():
    sample = PROJECT_ROOT / "backend" / "runtime" / "uploads" / "audio" / "6411aa92224b4af3bb3e1676caed226d_Standard_recording_1.mp3"
    result = analyze_audio(str(sample), sample.name)
    assert result["prediction"] == "REAL"
    assert result["confidence"] >= 0.9


def test_news_service_reports_high_confidence_for_obvious_fake_case():
    result = analyze_news_text_input(
        "Viral message claims a secret cure was hidden",
        "The post says everyone must share this hidden truth immediately.",
    )
    assert result["prediction"] == "FAKE"
    assert result["confidence"] >= 0.9


def test_news_service_reports_high_confidence_for_obvious_real_case():
    result = analyze_news_text_input(
        "Official policy update",
        "Scientists published a peer-reviewed study with methods and evidence.",
    )
    assert result["prediction"] == "REAL"
    assert result["confidence"] >= 0.9
