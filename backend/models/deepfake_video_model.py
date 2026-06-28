from __future__ import annotations

from typing import Any, Optional

from backend.utils.scoring import FAKE_FILENAME_TERMS, REAL_FILENAME_TERMS, calibrated_confidence, clamp, filename_terms
from backend.utils.video_processing import extract_video_features


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def analyze_video(
    file_path: str,
    original_name: str,
    source_url: Optional[str] = None,
    source_credibility: Optional[dict[str, Any]] = None,
) -> dict[str, object]:
    features = extract_video_features(file_path)
    original_fake_terms = filename_terms(original_name, FAKE_FILENAME_TERMS)
    original_real_terms = filename_terms(original_name, REAL_FILENAME_TERMS)
    merged_fake_terms = sorted(set(features["filename_fake_terms"]) | set(original_fake_terms))
    merged_real_terms = sorted(set(features["filename_real_terms"]) | set(original_real_terms))
    features["filename_fake_terms"] = merged_fake_terms
    features["filename_real_terms"] = merged_real_terms
    source_credibility = source_credibility or {}
    compression_context = bool(features.get("compression_distribution_context"))
    strong_structure = bool(features["has_video_track"] and features["moov_present"] and features["mdat_present"])
    reliable_sampling = features["frame_sampling_mode"] == "opencv-frame-sampling"
    source_score = source_credibility.get("score")
    source_score_value = float(source_score) if source_score is not None else None

    generation_marker_score = float(features["generation_marker_score"])
    temporal_consistency_proxy = float(features["temporal_consistency_proxy"])
    lighting_mismatch_proxy = float(features["lighting_mismatch_proxy"])
    audio_video_sync_proxy = float(features["audio_video_sync_proxy"])
    facial_inconsistency_proxy = float(features["facial_inconsistency_proxy"])
    lip_sync_proxy = float(features["lip_sync_proxy"])
    visual_artifact_proxy = float(features.get("visual_artifact_proxy", 0.0))
    face_presence_ratio = float(features.get("face_presence_ratio", 0.0))
    no_face_frame_ratio = float(features.get("no_face_frame_ratio", 0.0))
    mean_mouth_motion = float(features.get("mean_mouth_motion", 0.0))
    low_quality_proxy = float(features.get("low_quality_proxy", 0.0) or 0.0)
    frozen_speech_proxy = float(features.get("frozen_speech_proxy", 0.0))
    suspicious_window_count = int(features["suspicious_window_count"])
    suspicious_frame_count = int(features.get("suspicious_frame_count", 0) or 0)
    ai_export_markers = list(features["ai_export_markers"])
    frozen_speech_bundle = bool(
        frozen_speech_proxy >= 0.62
        and (
            visual_artifact_proxy >= 0.18
            or facial_inconsistency_proxy >= 0.28
            or temporal_consistency_proxy >= 0.4
            or lip_sync_proxy >= 0.22
            or suspicious_window_count >= 1
            or suspicious_frame_count >= 1
        )
    )
    strong_frozen_speech_bundle = bool(
        frozen_speech_bundle
        and face_presence_ratio >= 0.9
        and mean_mouth_motion <= 0.008
        and (visual_artifact_proxy >= 0.18 or facial_inconsistency_proxy >= 0.3 or temporal_consistency_proxy >= 0.42)
    )
    frozen_speech_support = frozen_speech_proxy if frozen_speech_bundle else round(frozen_speech_proxy * 0.18, 3)

    filename_fake_score = min(len(merged_fake_terms) * 0.12, 0.28)
    filename_real_credit = min(len(merged_real_terms) * 0.05, 0.12)

    artifact_branch = clamp(
        generation_marker_score * 0.4
        + visual_artifact_proxy * 0.38
        + frozen_speech_support * 0.36
        + min(suspicious_window_count * 0.08, 0.24)
        + min(suspicious_frame_count * 0.09, 0.24)
        + facial_inconsistency_proxy * 0.12
        + lip_sync_proxy * 0.1,
        0.0,
        1.0,
    )
    temporal_branch = clamp(
        temporal_consistency_proxy * 0.54
        + lighting_mismatch_proxy * 0.18
        + audio_video_sync_proxy * 0.18
        + frozen_speech_support * 0.1
        + (0.08 if suspicious_window_count >= 2 else 0.0)
        + (0.06 if suspicious_frame_count >= 2 else 0.0),
        0.0,
        1.0,
    )
    structural_risk = clamp(
        (0.08 if features["extension"] in {"webm", "mkv"} else 0.0)
        + (0.07 if features["size_mb"] < 2 and not compression_context else 0.02 if features["size_mb"] < 2 else 0.0)
        + (0.03 if 2 <= features["size_mb"] < 6 and not compression_context else 0.0)
        + (0.08 if features["unique_byte_ratio"] < 0.15 else 0.0)
        + (0.04 if features["repeated_byte_ratio"] > 0.95 and not compression_context else 0.0)
        + (0.08 if "ftyp" not in str(features["header_signature"]) and features["extension"] in {"mp4", "mov"} else 0.0)
        + (0.08 if not features["has_audio_track"] and (features["duration_seconds"] or 0) > 4 else 0.0)
        + (0.12 if not features["has_video_track"] else 0.0)
        + (0.05 if not features["moov_present"] or not features["mdat_present"] else 0.0)
        + (0.12 if (features["duration_seconds"] or 0) < 0.5 else 0.0)
        + (0.06 if 0.5 <= (features["duration_seconds"] or 0) < 3 else 0.0)
        + (0.05 if no_face_frame_ratio >= 0.55 and features["has_audio_track"] and reliable_sampling else 0.0),
        0.0,
        1.0,
    )
    real_support = clamp(
        (0.16 if strong_structure else 0.0)
        + (0.08 if strong_structure and features["extension"] in {"mp4", "mov"} else 0.0)
        + (0.08 if features["has_audio_track"] and features["has_video_track"] else 0.0)
        + (0.08 if compression_context else 0.0)
        + (0.05 if reliable_sampling else 0.0)
        + (
            0.05
            if suspicious_window_count == 0
            and suspicious_frame_count == 0
            and visual_artifact_proxy < 0.18
            and generation_marker_score < 0.12
            and not frozen_speech_bundle
            else 0.0
        )
        + (0.04 if face_presence_ratio >= 0.5 and no_face_frame_ratio < 0.35 else 0.0),
        0.0,
        1.0,
    )
    source_adjustment = 0.0
    if source_score_value is not None:
        if source_score_value <= 0.35:
            source_adjustment = 0.08
        elif source_score_value >= 0.82:
            source_adjustment = -0.04

    score = (
        0.1
        + filename_fake_score
        - filename_real_credit
        + artifact_branch * 0.42
        + temporal_branch * 0.26
        + structural_risk * 0.18
        - real_support * 0.18
        + source_adjustment
    )
    if frozen_speech_bundle and frozen_speech_proxy >= 0.52:
        score += 0.14
    if frozen_speech_bundle and frozen_speech_proxy >= 0.62 and face_presence_ratio >= 0.85:
        score += 0.16
    if strong_frozen_speech_bundle:
        score += 0.18
    if len(merged_fake_terms) >= 2:
        score += 0.12
        if not features["moov_present"] or not features["mdat_present"]:
            score += 0.08
    if ai_export_markers:
        score += min(len(ai_export_markers) * 0.08, 0.16)
    if artifact_branch >= 0.4 and strong_structure:
        score += 0.08
    if visual_artifact_proxy >= 0.5 and temporal_consistency_proxy >= 0.42 and suspicious_frame_count >= 2:
        score += 0.08
    if visual_artifact_proxy >= 0.48 and facial_inconsistency_proxy >= 0.42:
        score += 0.05
    if generation_marker_score >= 0.32 and (
        temporal_consistency_proxy >= 0.32 or facial_inconsistency_proxy >= 0.3 or lip_sync_proxy >= 0.28
    ):
        score += 0.08
    if suspicious_window_count + suspicious_frame_count >= 3:
        score += 0.06
    if compression_context and not frozen_speech_bundle and artifact_branch < 0.28 and temporal_branch < 0.3:
        score -= 0.08
    if (
        compression_context
        and not frozen_speech_bundle
        and not ai_export_markers
        and suspicious_window_count == 0
        and suspicious_frame_count == 0
    ):
        score -= 0.06
    compression_low_quality_relief = bool(
        compression_context
        and low_quality_proxy >= 0.42
        and not ai_export_markers
        and generation_marker_score < 0.18
        and suspicious_window_count <= 1
        and suspicious_frame_count <= 1
        and visual_artifact_proxy < 0.58
        and not frozen_speech_bundle
    )
    if compression_low_quality_relief:
        score -= 0.12 + min(low_quality_proxy * 0.08, 0.08)

    fake_probability = round(clamp(score, 0.03, 0.97), 2)
    real_probability = round(1 - fake_probability, 2)
    if (
        artifact_branch >= 0.45
        or frozen_speech_bundle
        or suspicious_window_count >= 2
        or suspicious_frame_count >= 2
        or ai_export_markers
        or (visual_artifact_proxy >= 0.5 and temporal_consistency_proxy >= 0.42)
    ):
        decision_threshold = 0.48
    elif compression_context and not frozen_speech_bundle and artifact_branch < 0.28 and temporal_branch < 0.3:
        decision_threshold = 0.57
    else:
        decision_threshold = 0.52
    if compression_low_quality_relief:
        decision_threshold = min(0.62, decision_threshold + 0.05)
    if strong_frozen_speech_bundle:
        decision_threshold = min(decision_threshold, 0.46)
    status = "Fake" if fake_probability >= decision_threshold else "Real"
    prediction = "FAKE" if status == "Fake" else "REAL"

    prediction_trace = {
        "filename_fake_score": round(filename_fake_score, 3),
        "filename_real_credit": round(filename_real_credit, 3),
        "artifact_branch": round(artifact_branch, 3),
        "temporal_branch": round(temporal_branch, 3),
        "structural_risk": round(structural_risk, 3),
        "real_support": round(real_support, 3),
        "frozen_speech_proxy": round(frozen_speech_proxy, 3),
        "frozen_speech_bundle": int(frozen_speech_bundle),
        "low_quality_proxy": round(low_quality_proxy, 3),
        "compression_low_quality_relief": int(compression_low_quality_relief),
        "source_adjustment": round(source_adjustment, 3),
        "decision_threshold": round(decision_threshold, 2),
        "opencv_ready": int(reliable_sampling),
    }
    if prediction == "FAKE":
        support_score = min(
            1.0,
            artifact_branch * 0.46
            + temporal_branch * 0.28
            + structural_risk * 0.14
            + frozen_speech_support * 0.18
            + min(len(merged_fake_terms) * 0.16, 0.24)
            + (0.08 if len(ai_export_markers) else 0.0)
            + (0.12 if fake_probability >= 0.75 else 0.0),
        )
        contradiction_score = min(
            1.0,
            real_support * 0.56
            + (0.1 if compression_context else 0.0)
            + (0.08 if face_presence_ratio >= 0.55 and no_face_frame_ratio < 0.3 else 0.0),
        )
    else:
        support_score = min(
            1.0,
            real_support * 0.56
            + (0.08 if compression_context else 0.0)
            + (0.08 if reliable_sampling else 0.0)
            + (0.08 if real_probability >= 0.85 else 0.0),
        )
        contradiction_score = min(
            1.0,
            artifact_branch * 0.38
            + temporal_branch * 0.24
            + frozen_speech_support * 0.16
            + min(len(merged_fake_terms) * 0.14, 0.24),
        )
    confidence = calibrated_confidence(
        fake_probability,
        decision_threshold,
        support_score,
        contradiction_score,
        floor=0.58,
        ceiling=0.99,
        base=0.62,
        precision=2,
    )
    if prediction == "FAKE" and (len(ai_export_markers) >= 1 or artifact_branch >= 0.55):
        confidence = max(confidence, 0.9)
    if prediction == "FAKE" and strong_frozen_speech_bundle:
        confidence = max(confidence, 0.91)
    if prediction == "FAKE" and len(merged_fake_terms) >= 2 and (not features["moov_present"] or not features["mdat_present"]):
        confidence = max(confidence, 0.91)

    reasons = [
        "AI Shield analyzed the clip in real time using fast video forensics and combined frame-level and stream-level signals.",
        "The video module blends artifact, temporal, and structural branches to estimate deepfake risk rather than trusting container structure alone.",
    ]
    if features["frame_sampling_mode"] == "opencv-frame-sampling":
        _append_reason(reasons, "OpenCV frame sampling was available, so sampled frames were inspected for face stability and visual inconsistencies.")
    else:
        _append_reason(reasons, "OpenCV frame decoding was not available in this runtime, so AI Shield used a lower-level stream forensics fallback.")
    if merged_fake_terms:
        _append_reason(reasons, f"Filename cues associated with synthetic media were detected: {', '.join(merged_fake_terms)}.")
    if features["size_mb"] < 2:
        _append_reason(reasons, "Small video payloads can indicate heavily recompressed or generated media.")
    if features["duration_seconds"] is not None:
        _append_reason(
            reasons,
            f"Estimated duration is {features['duration_seconds']} seconds at about {features['bitrate_kbps']} kbps.",
        )
    if features["unique_byte_ratio"] < 0.15 or features["repeated_byte_ratio"] > 0.95:
        _append_reason(reasons, "The sampled stream shows repetitive byte patterns that are less typical of natural camera footage.")
    if suspicious_window_count:
        _append_reason(
            reasons,
            f"{suspicious_window_count} suspicious sampled segments showed abrupt temporal or encoding inconsistencies.",
        )
    if suspicious_frame_count:
        _append_reason(reasons, f"{suspicious_frame_count} sampled frames crossed the frame-level anomaly threshold.")
    if float(features["temporal_consistency_proxy"]) >= 0.45:
        _append_reason(reasons, "Temporal consistency checks suggest abrupt scene-level changes that often appear in generated clips.")
    if float(features["facial_inconsistency_proxy"]) >= 0.35:
        _append_reason(reasons, "Sampled face regions shift or resize irregularly, which can indicate unstable generated facial synthesis.")
    if float(features["lighting_mismatch_proxy"]) >= 0.35:
        _append_reason(reasons, "Lighting and intensity proxy checks show irregular transitions between sampled segments.")
    if float(features["lip_sync_proxy"]) >= 0.28:
        _append_reason(reasons, "Mouth-motion consistency looks weak relative to the sampled clip structure, which raises lip-sync concerns.")
    if frozen_speech_bundle:
        _append_reason(
            reasons,
            "A face stayed visible through most sampled frames while mouth movement remained nearly frozen despite an audio track, which is suspicious for a talking-face clip.",
        )
    if no_face_frame_ratio >= 0.55 and reliable_sampling:
        _append_reason(reasons, "Many sampled frames did not preserve a stable face region, which increases manipulation risk for face-centric clips.")
    if float(features["audio_video_sync_proxy"]) >= 0.5:
        _append_reason(reasons, "Audio-track structure looks weak for the clip duration, which can point to synthetic or mismatched media.")
    if ai_export_markers:
        _append_reason(reasons, f"Export markers linked to AI/media generation workflows were found: {', '.join(ai_export_markers)}.")
    if source_score_value is not None and source_score_value <= 0.4:
        _append_reason(reasons, "The source domain credibility is low, which increases the overall risk score for this media.")
    if source_score_value is not None and source_score_value >= 0.78:
        _append_reason(reasons, "The source domain has strong credibility signals, so it slightly reduced the final fake probability.")
    if source_url:
        _append_reason(reasons, "Source URL context was blended with the video forensics result.")
    if compression_low_quality_relief:
        _append_reason(
            reasons,
            "Heavy compression and low visual quality were detected, so AI Shield reduced artifact penalties to avoid over-flagging degraded real footage.",
        )

    suspicious_segments = list(features["suspicious_segments"])
    if suspicious_segments:
        first_segment = suspicious_segments[0]
        if first_segment.get("estimated_second") is not None:
            _append_reason(
                reasons,
                f"A representative high-risk sample appears around {first_segment['estimated_second']} seconds into the clip.",
            )

    summary = (
        f"AI Shield classified the video '{original_name}' as {status.lower()} with "
        f"{int(fake_probability * 100)}% fake probability."
    )

    return {
        "analysis_type": "video",
        "content_type": "video",
        "status": status,
        "prediction": prediction,
        "fake_probability": fake_probability,
        "real_probability": real_probability,
        "confidence": confidence,
        "summary": summary,
        "reasons": reasons,
        "explanation": reasons,
        "source_credibility": source_credibility or None,
        "model": {
            "mode": "heuristic-video-ensemble" if features["frame_sampling_mode"] == "opencv-frame-sampling" else "heuristic-stream-fallback",
            "opencv_used": int(features["frame_sampling_mode"] == "opencv-frame-sampling"),
            "trained_backbone_loaded": 0,
            "ensemble_scores": prediction_trace,
        },
        "video_forensics": {
            "frame_sampling_mode": features["frame_sampling_mode"],
            "suspicious_segments": suspicious_segments,
            "signals": {
                "temporal_consistency_proxy": features["temporal_consistency_proxy"],
                "lighting_mismatch_proxy": features["lighting_mismatch_proxy"],
                "audio_video_sync_proxy": features["audio_video_sync_proxy"],
                "facial_inconsistency_proxy": features["facial_inconsistency_proxy"],
                "lip_sync_proxy": features["lip_sync_proxy"],
                "generation_marker_score": features["generation_marker_score"],
                "suspicious_segment_count": features["suspicious_window_count"],
                "suspicious_frame_count": features.get("suspicious_frame_count", 0),
                "visual_artifact_proxy": features.get("visual_artifact_proxy", 0.0),
                "frozen_speech_proxy": features.get("frozen_speech_proxy", 0.0),
                "frozen_speech_bundle": int(frozen_speech_bundle),
                "face_presence_ratio": features.get("face_presence_ratio", 0.0),
                "mean_mouth_motion": features.get("mean_mouth_motion", 0.0),
            },
        },
        "metadata": {
            **features,
            "prediction_trace": prediction_trace,
        },
    }
