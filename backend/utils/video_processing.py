from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path
from typing import Any, Optional, Tuple, Union

from backend.utils.scoring import FAKE_FILENAME_TERMS, REAL_FILENAME_TERMS, clamp, filename_terms

try:  # pragma: no cover - optional dependency in local runtime
    import cv2
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

try:  # pragma: no cover - optional dependency in local runtime
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None


WINDOW_SIZE = 8192
MAX_WINDOWS = 12
AI_EXPORT_MARKERS = (
    b"After Effects",
    b"CapCut",
    b"Canva",
    b"DeepFaceLab",
    b"Generated",
    b"HeyGen",
    b"Lavf",
    b"Pika",
    b"Runway",
    b"Synthesia",
)
SOCIAL_VIDEO_MARKERS = (b"WhatsApp", b"Telegram", b"Instagram", b"TikTok", b"Snapchat")
ATOM_MARKERS = ("ftyp", "moov", "mdat", "mvhd", "tkhd", "stts", "stss", "ctts", "soun", "vide", "avc1", "hvc1", "hev1", "vp09", "av01")
TRACK_MARKERS = ("edts", "elst", "mdia", "minf", "stbl")


def _shannon_entropy(chunk: bytes) -> float:
    if not chunk:
        return 0.0

    frequencies = {}
    for value in chunk:
        frequencies[value] = frequencies.get(value, 0) + 1

    entropy = 0.0
    total = float(len(chunk))
    for count in frequencies.values():
        probability = count / total
        entropy -= probability * math.log2(probability)
    return entropy


def _window_positions(file_size: int, window_size: int, count: int) -> list[int]:
    if file_size <= window_size or count <= 1:
        return [0]

    max_start = max(file_size - window_size, 0)
    return [round(index * max_start / max(count - 1, 1)) for index in range(count)]


def _sample_windows(file_bytes: bytes, duration_seconds: Optional[float]) -> Tuple[list[dict[str, Any]], dict[str, float]]:
    file_size = len(file_bytes)
    window_count = min(MAX_WINDOWS, max(4, file_size // (512 * 1024) + 2)) if file_size else 1
    positions = _window_positions(file_size, WINDOW_SIZE, window_count)

    windows: list[dict[str, Any]] = []
    entropy_values: list[float] = []
    unique_values: list[float] = []

    for index, start in enumerate(positions):
        chunk = file_bytes[start : start + WINDOW_SIZE]
        entropy = round(_shannon_entropy(chunk), 3)
        unique_ratio = round(len(set(chunk)) / 256, 3) if chunk else 0.0
        repeated_ratio = round((len(chunk) - len(set(chunk))) / len(chunk), 3) if chunk else 0.0
        average_byte = round(sum(chunk) / len(chunk), 2) if chunk else 0.0
        marker_hits = [marker.decode("latin-1", "ignore") for marker in AI_EXPORT_MARKERS if marker in chunk]

        windows.append(
            {
                "window_index": index + 1,
                "offset_bytes": start,
                "estimated_second": round((start / max(file_size, 1)) * duration_seconds, 2) if duration_seconds else None,
                "entropy": entropy,
                "unique_ratio": unique_ratio,
                "repeated_ratio": repeated_ratio,
                "average_byte": average_byte,
                "export_markers": marker_hits,
            }
        )
        entropy_values.append(entropy)
        unique_values.append(unique_ratio)

    entropy_mean = sum(entropy_values) / max(len(entropy_values), 1)
    average_unique = sum(unique_values) / max(len(unique_values), 1)
    average_brightness = sum(window["average_byte"] for window in windows) / max(len(windows), 1)

    suspicious_windows = []
    adjacent_jumps = 0
    lighting_jumps = 0

    for index, window in enumerate(windows):
        anomaly_score = 0.0
        if window["unique_ratio"] < 0.11:
            anomaly_score += 0.26
        if window["repeated_ratio"] > 0.985:
            anomaly_score += 0.18
        if abs(window["entropy"] - entropy_mean) > 0.9:
            anomaly_score += 0.16
        if abs(window["average_byte"] - average_brightness) > 24:
            anomaly_score += 0.12
        if window["export_markers"]:
            anomaly_score += 0.14

        if index:
            prior = windows[index - 1]
            if abs(window["entropy"] - prior["entropy"]) > 1.0:
                adjacent_jumps += 1
                anomaly_score += 0.1
            if abs(window["average_byte"] - prior["average_byte"]) > 30:
                lighting_jumps += 1

        if anomaly_score >= 0.28:
            suspicious_windows.append(
                {
                    "window_index": window["window_index"],
                    "estimated_second": window["estimated_second"],
                    "anomaly_score": round(clamp(anomaly_score, 0.0, 1.0), 2),
                    "reason": "Abrupt sampling-window inconsistency detected."
                    if abs(window["entropy"] - entropy_mean) > 0.9
                    else "Repeated or overly uniform encoding pattern detected.",
                }
            )

    summary = {
        "entropy_mean": round(entropy_mean, 3),
        "entropy_spread": round((max(entropy_values) - min(entropy_values)) if entropy_values else 0.0, 3),
        "average_unique_ratio": round(average_unique, 3),
        "adjacent_entropy_jumps": adjacent_jumps,
        "lighting_proxy_jumps": lighting_jumps,
        "suspicious_window_count": len(suspicious_windows),
        "sampling_window_count": len(windows),
    }

    return suspicious_windows[:4], summary


def _top_level_atoms(file_bytes: bytes) -> list[str]:
    atoms: list[str] = []
    cursor = 0
    while cursor + 8 <= len(file_bytes) and len(atoms) < 32:
        try:
            size = struct.unpack(">I", file_bytes[cursor : cursor + 4])[0]
        except struct.error:
            break

        atom_type = file_bytes[cursor + 4 : cursor + 8].decode("latin-1", errors="ignore").lower()
        if not atom_type.isprintable():
            break

        atoms.append(atom_type)
        if size < 8:
            break
        cursor += size
    return atoms


def _parse_duration_and_bitrate(file_bytes: bytes, file_size: int) -> Tuple[Optional[float], Optional[float]]:
    duration_seconds = None
    bitrate_kbps = None
    mvhd_index = file_bytes.find(b"mvhd")
    if mvhd_index != -1 and len(file_bytes) >= mvhd_index + 24:
        version = file_bytes[mvhd_index + 4]
        try:
            if version == 0:
                timescale = struct.unpack(">I", file_bytes[mvhd_index + 16 : mvhd_index + 20])[0]
                duration = struct.unpack(">I", file_bytes[mvhd_index + 20 : mvhd_index + 24])[0]
            else:
                timescale = struct.unpack(">I", file_bytes[mvhd_index + 28 : mvhd_index + 32])[0]
                duration = struct.unpack(">Q", file_bytes[mvhd_index + 32 : mvhd_index + 40])[0]
            if timescale:
                duration_seconds = round(duration / float(timescale), 2)
                bitrate_kbps = round((file_size * 8) / max(duration / float(timescale), 0.01) / 1000, 1)
        except (struct.error, ZeroDivisionError):
            duration_seconds = None
            bitrate_kbps = None
    return duration_seconds, bitrate_kbps


def _frame_positions(total_frames: int, sample_count: int) -> list[int]:
    if total_frames <= 0 or sample_count <= 1:
        return [0]

    max_index = max(total_frames - 1, 0)
    return [round(index * max_index / max(sample_count - 1, 1)) for index in range(sample_count)]


def _face_cascade() -> Any:
    if cv2 is None or not hasattr(cv2, "data"):
        return None

    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not cascade_path.exists():
        return None

    detector = cv2.CascadeClassifier(str(cascade_path))
    return None if detector.empty() else detector


def _extract_opencv_frame_features(
    file_path: str,
    duration_seconds: Optional[float],
    has_audio_track: int,
) -> dict[str, Any]:
    if cv2 is None or np is None:
        return {
            "available": False,
            "frame_sampling_mode": "byte-window-approximation",
            "opencv_ready": 0,
            "sampled_frame_count": 0,
            "fps": None,
            "total_frames": 0,
            "facial_inconsistency_proxy": 0.0,
            "lip_sync_proxy": 0.0,
            "lighting_proxy": 0.0,
            "temporal_proxy": 0.0,
            "suspicious_frames": [],
        }

    capture = cv2.VideoCapture(file_path)
    if not capture.isOpened():
        return {
            "available": False,
            "frame_sampling_mode": "byte-window-approximation",
            "opencv_ready": 1,
            "sampled_frame_count": 0,
            "fps": None,
            "total_frames": 0,
            "facial_inconsistency_proxy": 0.0,
            "lip_sync_proxy": 0.0,
            "lighting_proxy": 0.0,
            "temporal_proxy": 0.0,
            "suspicious_frames": [],
        }

    detector = _face_cascade()
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    sample_count = min(12, max(6, total_frames // 45 + 1)) if total_frames > 0 else 6
    positions = _frame_positions(total_frames, sample_count) if total_frames > 0 else [0] * sample_count

    previous_face_count = None
    previous_face_center = None
    previous_face_area = None
    previous_mouth_region = None
    brightness_values: list[float] = []
    sharpness_values: list[float] = []
    mouth_motion_values: list[float] = []
    suspicious_frames: list[dict[str, Any]] = []
    brightness_jump_count = 0
    face_count_changes = 0
    face_center_jumps = 0
    face_area_jumps = 0
    sampled_frame_count = 0
    face_detected_count = 0
    no_face_frame_count = 0
    low_sharpness_frame_count = 0
    suspicious_frame_score_total = 0.0

    try:
        for frame_index, position in enumerate(positions):
            if total_frames > 0:
                capture.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue

            sampled_frame_count += 1
            height, width = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = float(gray.mean())
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            brightness_values.append(brightness)
            sharpness_values.append(sharpness)

            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40)) if detector is not None else []
            face_count = len(faces)
            anomaly_score = 0.0
            reasons: list[str] = []
            estimated_second = round((position / fps), 2) if fps else (round((frame_index / max(sample_count - 1, 1)) * duration_seconds, 2) if duration_seconds else None)

            if previous_face_count is not None and face_count != previous_face_count:
                face_count_changes += 1
                anomaly_score += 0.1
                reasons.append("Detected face count changes abruptly across sampled frames.")
            previous_face_count = face_count

            if sharpness < 12:
                low_sharpness_frame_count += 1
                anomaly_score += 0.12
                reasons.append("Frame sharpness is unusually low around the detected face region.")

            if len(brightness_values) > 1 and abs(brightness_values[-1] - brightness_values[-2]) > 48:
                brightness_jump_count += 1
                anomaly_score += 0.12
                reasons.append("Lighting intensity shifts abruptly between adjacent sampled frames.")

            if face_count:
                face_detected_count += 1
                x, y, w, h = max(faces, key=lambda candidate: candidate[2] * candidate[3])
                face_area = (w * h) / float(max(width * height, 1))
                face_center = ((x + w / 2) / max(width, 1), (y + h / 2) / max(height, 1))

                if previous_face_center is not None:
                    center_shift = abs(face_center[0] - previous_face_center[0]) + abs(face_center[1] - previous_face_center[1])
                    if center_shift > 0.18:
                        face_center_jumps += 1
                        anomaly_score += 0.18
                        reasons.append("Largest detected face moves unusually far between sampled frames.")

                if previous_face_area is not None and abs(face_area - previous_face_area) > 0.16:
                    face_area_jumps += 1
                    anomaly_score += 0.14
                    reasons.append("Detected face scale changes abruptly across sampled frames.")

                previous_face_center = face_center
                previous_face_area = face_area

                mouth_top = y + int(h * 0.58)
                mouth_region = gray[mouth_top : y + h, x : x + w]
                if previous_mouth_region is not None and mouth_region.size and mouth_region.shape == previous_mouth_region.shape:
                    mouth_motion = float(np.mean(cv2.absdiff(mouth_region, previous_mouth_region))) / 255.0
                    mouth_motion_values.append(mouth_motion)
                    if has_audio_track and mouth_motion < 0.01:
                        anomaly_score += 0.12
                        reasons.append("Mouth movement stays unusually static even though an audio track is present.")
                previous_mouth_region = mouth_region.copy() if mouth_region.size else None
            else:
                no_face_frame_count += 1
                previous_face_center = None
                previous_face_area = None
                previous_mouth_region = None
                anomaly_score += 0.08
                reasons.append("No stable face was detected in the sampled frame.")

            if anomaly_score >= 0.28:
                suspicious_frame_score_total += clamp(anomaly_score, 0.0, 1.0)
                suspicious_frames.append(
                    {
                        "window_index": frame_index + 1,
                        "frame_label": f"Frame sample {frame_index + 1}",
                        "estimated_second": estimated_second,
                        "anomaly_score": round(clamp(anomaly_score, 0.0, 1.0), 2),
                        "reason": reasons[0] if reasons else "Suspicious frame inconsistency detected.",
                    }
                )
    finally:
        capture.release()

    brightness_spread = ((max(brightness_values) - min(brightness_values)) / 255.0) if brightness_values else 0.0
    sharpness_spread = clamp(((max(sharpness_values) - min(sharpness_values)) / 250.0) if sharpness_values else 0.0, 0.0, 1.0)
    mean_sharpness = sum(sharpness_values) / max(len(sharpness_values), 1)
    mean_mouth_motion = sum(mouth_motion_values) / max(len(mouth_motion_values), 1)
    face_presence_ratio = face_detected_count / max(sampled_frame_count, 1)
    no_face_frame_ratio = no_face_frame_count / max(sampled_frame_count, 1)
    low_sharpness_frame_ratio = low_sharpness_frame_count / max(sampled_frame_count, 1)
    suspicious_frame_count = len(suspicious_frames)
    suspicious_frame_score_mean = suspicious_frame_score_total / max(suspicious_frame_count, 1)

    return {
        "available": sampled_frame_count > 0,
        "frame_sampling_mode": "opencv-frame-sampling" if sampled_frame_count > 0 else "byte-window-approximation",
        "opencv_ready": 1,
        "sampled_frame_count": sampled_frame_count,
        "fps": round(fps, 2) if fps else None,
        "total_frames": total_frames,
        "face_presence_ratio": round(clamp(face_presence_ratio, 0.0, 1.0), 2),
        "no_face_frame_ratio": round(clamp(no_face_frame_ratio, 0.0, 1.0), 2),
        "mean_sharpness": round(max(mean_sharpness, 0.0), 2),
        "low_sharpness_frame_ratio": round(clamp(low_sharpness_frame_ratio, 0.0, 1.0), 2),
        "mean_mouth_motion": round(clamp(mean_mouth_motion, 0.0, 1.0), 3),
        "suspicious_frame_count": suspicious_frame_count,
        "suspicious_frame_score_mean": round(clamp(suspicious_frame_score_mean, 0.0, 1.0), 2),
        "facial_inconsistency_proxy": round(clamp(face_count_changes * 0.16 + face_center_jumps * 0.14 + face_area_jumps * 0.12, 0.0, 1.0), 2),
        "lip_sync_proxy": round(clamp((0.24 if has_audio_track and mean_mouth_motion < 0.02 else 0.0) + mean_mouth_motion * 0.4, 0.0, 1.0), 2),
        "lighting_proxy": round(clamp(brightness_spread * 0.7 + brightness_jump_count * 0.08, 0.0, 1.0), 2),
        "temporal_proxy": round(clamp(face_center_jumps * 0.14 + face_count_changes * 0.12 + sharpness_spread * 0.2, 0.0, 1.0), 2),
        "suspicious_frames": suspicious_frames[:4],
    }


def extract_video_features(file_path: str) -> dict[str, Union[float, int, str, list[dict[str, Any]], list[str]]]:
    path = Path(file_path)
    file_size = path.stat().st_size
    file_bytes = path.read_bytes()

    hasher = hashlib.sha256()
    sample = file_bytes[:16384]
    hasher.update(sample[:4096])

    unique_byte_ratio = round(len(set(sample)) / 256, 3) if sample else 0.0
    repeated_byte_ratio = round((len(sample) - len(set(sample))) / len(sample), 3) if sample else 0.0
    ascii_header = sample[:32].decode("latin1", errors="ignore").lower()
    duration_seconds, bitrate_kbps = _parse_duration_and_bitrate(file_bytes, file_size)

    top_level_atoms = _top_level_atoms(file_bytes[: min(len(file_bytes), 2_000_000)])
    marker_hits = {
        marker: int(marker.encode("latin-1") in file_bytes)
        for marker in ATOM_MARKERS
    }
    track_marker_hits = {
        marker: int(marker.encode("latin-1") in file_bytes)
        for marker in TRACK_MARKERS
    }
    suspicious_windows, window_summary = _sample_windows(file_bytes, duration_seconds)

    ai_export_hits = [marker.decode("latin-1", "ignore") for marker in AI_EXPORT_MARKERS if marker in file_bytes]
    social_hits = [marker.decode("latin-1", "ignore") for marker in SOCIAL_VIDEO_MARKERS if marker in file_bytes]
    has_audio_track = int(bool(marker_hits.get("soun") or b"mp4a" in file_bytes))
    has_video_track = int(bool(marker_hits.get("vide") or marker_hits.get("avc1") or marker_hits.get("hvc1") or marker_hits.get("vp09") or marker_hits.get("av01")))
    opencv_summary = _extract_opencv_frame_features(file_path, duration_seconds, has_audio_track)
    compression_distribution_context = int(
        bool(
            (b"beam" in file_bytes or "whatsapp" in path.name.lower())
            and has_audio_track
            and has_video_track
            and marker_hits["moov"]
            and marker_hits["mdat"]
            and not ai_export_hits
        )
    )

    codec = "unknown"
    for codec_marker in ("av01", "vp09", "hvc1", "hev1", "avc1"):
        if marker_hits.get(codec_marker):
            codec = codec_marker
            break

    facial_inconsistency_proxy = float(opencv_summary["facial_inconsistency_proxy"])
    lip_sync_proxy = float(opencv_summary["lip_sync_proxy"])
    temporal_opencv_proxy = float(opencv_summary["temporal_proxy"])
    lighting_opencv_proxy = float(opencv_summary["lighting_proxy"])
    face_presence_ratio = float(opencv_summary.get("face_presence_ratio", 0.0) or 0.0)
    no_face_frame_ratio = float(opencv_summary.get("no_face_frame_ratio", 0.0) or 0.0)
    mean_sharpness = float(opencv_summary.get("mean_sharpness", 0.0) or 0.0)
    low_sharpness_frame_ratio = float(opencv_summary.get("low_sharpness_frame_ratio", 0.0) or 0.0)
    mean_mouth_motion = float(opencv_summary.get("mean_mouth_motion", 0.0) or 0.0)
    suspicious_frame_count = int(opencv_summary.get("suspicious_frame_count", 0) or 0)
    suspicious_frame_score_mean = float(opencv_summary.get("suspicious_frame_score_mean", 0.0) or 0.0)
    suspicious_segments = opencv_summary["suspicious_frames"] or suspicious_windows
    window_temporal_proxy = clamp(window_summary["adjacent_entropy_jumps"] * 0.14 + window_summary["entropy_spread"] * 0.18, 0.0, 1.0)
    window_lighting_proxy = clamp(window_summary["lighting_proxy_jumps"] * 0.16 + window_summary["entropy_spread"] * 0.08, 0.0, 1.0)

    if compression_distribution_context:
        facial_inconsistency_proxy = round(facial_inconsistency_proxy * 0.5, 2)
        lip_sync_proxy = round(lip_sync_proxy * 0.75, 2)
        temporal_opencv_proxy = round(temporal_opencv_proxy * 0.55, 2)
        lighting_opencv_proxy = round(lighting_opencv_proxy * 0.7, 2)
        suspicious_frame_score_mean = round(suspicious_frame_score_mean * 0.7, 2)
        window_temporal_proxy = clamp(window_summary["adjacent_entropy_jumps"] * 0.08 + window_summary["entropy_spread"] * 0.08, 0.0, 1.0)
        window_lighting_proxy = clamp(window_summary["lighting_proxy_jumps"] * 0.08 + window_summary["entropy_spread"] * 0.04, 0.0, 1.0)
        suspicious_segments = [segment for segment in suspicious_segments if float(segment.get("anomaly_score", 0.0)) >= 0.34]

    temporal_consistency_proxy = round(max(window_temporal_proxy, temporal_opencv_proxy), 2)
    lighting_mismatch_proxy = round(max(window_lighting_proxy, lighting_opencv_proxy), 2)
    normalized_entropy_hint = round(clamp(window_summary["entropy_mean"] / 8.0, 0.0, 1.0), 3)
    frozen_speech_proxy = round(
        clamp(
            (
                0.38
                + face_presence_ratio * 0.24
                + temporal_consistency_proxy * 0.18
                + no_face_frame_ratio * 0.08
            )
            if has_audio_track and face_presence_ratio >= 0.75 and mean_mouth_motion <= 0.008 and opencv_summary["sampled_frame_count"] >= 6
            else 0.0,
            0.0,
            1.0,
        ),
        2,
    )
    visual_artifact_proxy = round(
        clamp(
            suspicious_frame_score_mean * 0.32
            + min(suspicious_frame_count * 0.09, 0.28)
            + facial_inconsistency_proxy * 0.18
            + lip_sync_proxy * 0.14
            + no_face_frame_ratio * (0.18 if has_audio_track else 0.08)
            + max(0.0, 0.03 - mean_mouth_motion) * (4.0 if has_audio_track else 1.5),
            0.0,
            1.0,
        ),
        2,
    )
    low_quality_proxy = round(
        clamp(
            (0.08 if compression_distribution_context else 0.0)
            + (0.18 if bitrate_kbps and bitrate_kbps < 900 else 0.0)
            + (0.08 if bitrate_kbps and bitrate_kbps < 650 else 0.0)
            + (0.08 if file_size < 2_400_000 else 0.0)
            + low_sharpness_frame_ratio * 0.34
            + (0.1 if mean_sharpness and mean_sharpness < 18 else 0.0),
            0.0,
            1.0,
        ),
        2,
    )

    if (
        compression_distribution_context
        and low_quality_proxy >= 0.42
        and not ai_export_hits
        and face_presence_ratio >= 0.55
        and suspicious_frame_count <= 1
        and len(suspicious_segments) <= 1
    ):
        facial_inconsistency_proxy = round(facial_inconsistency_proxy * 0.82, 2)
        temporal_consistency_proxy = round(temporal_consistency_proxy * 0.86, 2)
        lighting_mismatch_proxy = round(lighting_mismatch_proxy * 0.82, 2)
        visual_artifact_proxy = round(max(0.0, visual_artifact_proxy - min(0.18, low_quality_proxy * 0.28)), 2)

    return {
        "extension": path.suffix.lower().replace(".", ""),
        "size_bytes": file_size,
        "size_mb": round(file_size / (1024 * 1024), 2),
        "hash_seed": int(hasher.hexdigest()[:8], 16),
        "name_length": len(path.name),
        "filename": path.name,
        "filename_fake_terms": filename_terms(path.name, FAKE_FILENAME_TERMS),
        "filename_real_terms": filename_terms(path.name, REAL_FILENAME_TERMS),
        "unique_byte_ratio": unique_byte_ratio,
        "repeated_byte_ratio": repeated_byte_ratio,
        "header_signature": ascii_header.strip(),
        "duration_seconds": duration_seconds,
        "bitrate_kbps": bitrate_kbps,
        "has_beam_atom": int(b"beam" in file_bytes),
        "has_whatsapp_marker": int(bool("whatsapp" in path.name.lower() or social_hits)),
        "entropy_hint": normalized_entropy_hint,
        "top_level_atoms": top_level_atoms,
        "codec": codec,
        "has_audio_track": has_audio_track,
        "has_video_track": has_video_track,
        "moov_present": marker_hits["moov"],
        "mdat_present": marker_hits["mdat"],
        "stts_present": marker_hits["stts"],
        "stss_present": marker_hits["stss"],
        "ctts_present": marker_hits["ctts"],
        "track_structure_markers": [marker for marker, present in track_marker_hits.items() if present],
        "ai_export_markers": ai_export_hits,
        "social_distribution_markers": social_hits,
        "compression_distribution_context": compression_distribution_context,
        "frame_sampling_mode": opencv_summary["frame_sampling_mode"],
        "opencv_ready": opencv_summary["opencv_ready"],
        "sampled_frame_count": opencv_summary["sampled_frame_count"],
        "fps": opencv_summary["fps"],
        "total_frames": opencv_summary["total_frames"],
        "face_presence_ratio": round(face_presence_ratio, 2),
        "no_face_frame_ratio": round(no_face_frame_ratio, 2),
        "mean_sharpness": round(max(mean_sharpness, 0.0), 2),
        "low_sharpness_frame_ratio": round(clamp(low_sharpness_frame_ratio, 0.0, 1.0), 2),
        "mean_mouth_motion": round(mean_mouth_motion, 3),
        "low_quality_proxy": low_quality_proxy,
        "suspicious_frame_count": suspicious_frame_count,
        "suspicious_frame_score_mean": round(suspicious_frame_score_mean, 2),
        "facial_inconsistency_proxy": facial_inconsistency_proxy,
        "lip_sync_proxy": lip_sync_proxy,
        "temporal_consistency_proxy": temporal_consistency_proxy,
        "lighting_mismatch_proxy": lighting_mismatch_proxy,
        "frozen_speech_proxy": frozen_speech_proxy,
        "visual_artifact_proxy": visual_artifact_proxy,
        "audio_video_sync_proxy": round(
            clamp(
                (0.45 if not has_audio_track and (duration_seconds or 0) > 4 else 0.05)
                + (0.02 if compression_distribution_context and bitrate_kbps and bitrate_kbps < 850 else 0.05 if bitrate_kbps and bitrate_kbps < 850 else 0.0),
                0.0,
                1.0,
            ),
            2,
        ),
        "generation_marker_score": round(clamp(len(ai_export_hits) * 0.22 + len(filename_terms(path.name, {"ai", "deepfake", "generated", "synthetic"})) * 0.12, 0.0, 1.0), 2),
        "window_entropy_spread": window_summary["entropy_spread"],
        "adjacent_entropy_jumps": window_summary["adjacent_entropy_jumps"],
        "lighting_proxy_jumps": window_summary["lighting_proxy_jumps"],
        "sampling_window_count": window_summary["sampling_window_count"],
        "suspicious_window_count": len(suspicious_segments),
        "suspicious_segments": suspicious_segments,
    }
