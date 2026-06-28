from __future__ import annotations

import hashlib
import wave
from array import array
from contextlib import suppress
from pathlib import Path
from typing import Any, Optional

from backend.utils.scoring import FAKE_FILENAME_TERMS, REAL_FILENAME_TERMS, clamp, filename_terms

try:  # pragma: no cover - optional dependency in local runtime
    import librosa
except Exception:  # pragma: no cover - optional dependency
    librosa = None

try:  # pragma: no cover - optional dependency in local runtime
    import numpy as np
except Exception:  # pragma: no cover - optional dependency
    np = None


def _array_to_float_samples(values: array, max_amplitude: float) -> list[float]:
    return [sample / max_amplitude for sample in values]


def _mean(values: list[float]) -> float:
    return sum(values) / max(len(values), 1)


def _std(values: list[float], average: Optional[float] = None) -> float:
    if not values:
        return 0.0
    avg = _mean(values) if average is None else average
    return (sum((value - avg) ** 2 for value in values) / len(values)) ** 0.5


def _normalize_waveform(samples: Any) -> Any:
    if np is None or samples is None or not len(samples):
        return samples
    peak = float(np.max(np.abs(samples))) or 1.0
    return samples / peak


def _noise_gate(samples: Any) -> Any:
    if np is None or samples is None or not len(samples):
        return samples
    floor = float(np.percentile(np.abs(samples), 20))
    threshold = max(0.004, floor * 1.75)
    filtered = np.where(np.abs(samples) < threshold, 0.0, samples)
    return filtered.astype("float32")


def _pause_segments_from_energy(energy: Any, sr: int, hop_length: int) -> tuple[list[dict[str, float]], float]:
    if np is None or energy is None or not len(energy):
        return [], 0.0

    threshold = max(float(np.percentile(energy, 18)), 0.012)
    segments: list[dict[str, float]] = []
    start_index: Optional[int] = None

    for index, value in enumerate(energy):
        if value <= threshold:
            if start_index is None:
                start_index = index
            continue

        if start_index is not None:
            duration = ((index - start_index) * hop_length) / float(sr)
            if 0.06 <= duration <= 0.5:
                segments.append(
                    {
                        "start_second": round((start_index * hop_length) / float(sr), 2),
                        "end_second": round((index * hop_length) / float(sr), 2),
                        "duration_seconds": round(duration, 2),
                        "reason": "Natural pause / breathing-style gap detected.",
                    }
                )
            start_index = None

    if start_index is not None:
        duration = ((len(energy) - start_index) * hop_length) / float(sr)
        if 0.06 <= duration <= 0.5:
            segments.append(
                {
                    "start_second": round((start_index * hop_length) / float(sr), 2),
                    "end_second": round((len(energy) * hop_length) / float(sr), 2),
                    "duration_seconds": round(duration, 2),
                    "reason": "Natural pause / breathing-style gap detected.",
                }
            )

    pause_ratio = round(sum(segment["duration_seconds"] for segment in segments), 4)
    return segments[:5], pause_ratio


def _load_audio_with_librosa(file_path: str) -> dict[str, Any]:
    if librosa is None or np is None:
        return {"available": False}
    try:
        samples, sample_rate = librosa.load(file_path, sr=16000, mono=True)
        if samples is None or not len(samples):
            return {"available": False}

        normalized = _normalize_waveform(samples.astype("float32"))
        denoised = _noise_gate(normalized)
        duration_seconds = round(float(len(denoised)) / float(sample_rate), 2)
        frame_length = 1024
        hop_length = 256

        rms = librosa.feature.rms(y=denoised, frame_length=frame_length, hop_length=hop_length)[0]
        zcr = librosa.feature.zero_crossing_rate(denoised, frame_length=frame_length, hop_length=hop_length)[0]
        spectral_centroid = librosa.feature.spectral_centroid(y=denoised, sr=sample_rate, hop_length=hop_length)[0]
        spectral_bandwidth = librosa.feature.spectral_bandwidth(y=denoised, sr=sample_rate, hop_length=hop_length)[0]
        spectral_flatness = librosa.feature.spectral_flatness(y=denoised, hop_length=hop_length)[0]
        mfcc = librosa.feature.mfcc(y=denoised, sr=sample_rate, n_mfcc=13, hop_length=hop_length)
        mel = librosa.feature.melspectrogram(y=denoised, sr=sample_rate, n_mels=64, hop_length=hop_length)
        chroma = librosa.feature.chroma_stft(y=denoised, sr=sample_rate, hop_length=hop_length)

        pitches = librosa.yin(denoised, fmin=70, fmax=380, sr=sample_rate, frame_length=frame_length, hop_length=hop_length)
        valid_pitches = pitches[np.isfinite(pitches)]
        pitch_mean = round(float(np.mean(valid_pitches)), 2) if valid_pitches.size else None
        pitch_std = round(float(np.std(valid_pitches)), 2) if valid_pitches.size else None

        pause_segments, pause_ratio = _pause_segments_from_energy(rms, sample_rate, hop_length)
        breathing_proxy = round(clamp(pause_ratio * 3.1 + float(np.std(rms)) * 1.8, 0.0, 1.0), 2)
        pitch_consistency_proxy = round(
            clamp((0.72 if valid_pitches.size and float(np.std(valid_pitches)) < 9 else 0.0) + (0.14 if valid_pitches.size and float(np.mean(valid_pitches)) > 265 else 0.0), 0.0, 1.0),
            2,
        )
        spectrogram_texture_proxy = round(
            clamp((0.58 if float(np.std(mfcc)) < 24 else 0.0) + (0.22 if float(np.std(chroma)) < 0.08 else 0.0) + (0.18 if float(np.mean(spectral_flatness)) < 0.05 else 0.0), 0.0, 1.0),
            2,
        )
        background_noise_proxy = round(
            clamp((0.64 if float(np.mean(spectral_flatness)) < 0.03 else 0.0) + (0.18 if float(np.std(spectral_flatness)) < 0.015 else 0.0), 0.0, 1.0),
            2,
        )
        micro_pause_absence_proxy = round(clamp((0.82 if duration_seconds > 2 and pause_ratio < 0.04 else 0.0) + (0.14 if len(pause_segments) < 2 and duration_seconds > 3 else 0.0), 0.0, 1.0), 2)
        robotic_tone_proxy = round(clamp(spectrogram_texture_proxy * 0.52 + pitch_consistency_proxy * 0.34, 0.0, 1.0), 2)

        suspicious_regions: list[dict[str, Any]] = []
        if micro_pause_absence_proxy >= 0.55:
            suspicious_regions.append(
                {
                    "segment_label": "Speech flow",
                    "estimated_second": round(duration_seconds / 2, 2),
                    "anomaly_score": micro_pause_absence_proxy,
                    "reason": "Very few natural micro-pauses were detected across the clip.",
                }
            )
        if pitch_consistency_proxy >= 0.5:
            suspicious_regions.append(
                {
                    "segment_label": "Pitch profile",
                    "estimated_second": round(duration_seconds / 3, 2),
                    "anomaly_score": pitch_consistency_proxy,
                    "reason": "Pitch contour appears overly stable for spontaneous human speech.",
                }
            )
        if spectrogram_texture_proxy >= 0.5:
            suspicious_regions.append(
                {
                    "segment_label": "Spectrogram texture",
                    "estimated_second": round(duration_seconds * 0.66, 2),
                    "anomaly_score": spectrogram_texture_proxy,
                    "reason": "Spectrogram texture looks smoother and more repetitive than natural speech.",
                }
            )

        absolute = np.abs(denoised)
        average_amplitude = round(float(np.mean(absolute)), 4)
        peak_amplitude = round(float(np.max(absolute)), 4)
        silence_ratio = round(float(np.mean(absolute <= 0.015)), 4)
        clipped_ratio = round(float(np.mean(absolute >= 0.96)), 4)

        return {
            "available": True,
            "feature_extractor": "librosa-mfcc-mel-chroma",
            "duration_seconds": duration_seconds,
            "sample_rate": sample_rate,
            "channels": 1,
            "sample_width": 2,
            "average_amplitude": average_amplitude,
            "peak_amplitude": peak_amplitude,
            "silence_ratio": silence_ratio,
            "clipped_ratio": clipped_ratio,
            "zero_crossing_rate": round(float(np.mean(zcr)), 4),
            "rms_mean": round(float(np.mean(rms)), 4),
            "rms_std": round(float(np.std(rms)), 4),
            "pitch_mean_hz": pitch_mean,
            "pitch_std_hz": pitch_std,
            "spectral_flatness_mean": round(float(np.mean(spectral_flatness)), 4),
            "spectral_centroid_mean": round(float(np.mean(spectral_centroid)), 2),
            "spectral_bandwidth_mean": round(float(np.mean(spectral_bandwidth)), 2),
            "mfcc_variability": round(float(np.std(mfcc)), 2),
            "mel_spectrogram_variability": round(float(np.std(librosa.power_to_db(mel + 1e-8))), 2),
            "chroma_variability": round(float(np.std(chroma)), 4),
            "breathing_pause_ratio": pause_ratio,
            "breathing_proxy": breathing_proxy,
            "pitch_consistency_proxy": pitch_consistency_proxy,
            "spectrogram_texture_proxy": spectrogram_texture_proxy,
            "background_noise_proxy": background_noise_proxy,
            "micro_pause_absence_proxy": micro_pause_absence_proxy,
            "robotic_tone_proxy": robotic_tone_proxy,
            "suspicious_regions": suspicious_regions,
        }
    except Exception:
        return {"available": False}


def _load_audio_with_wave(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    duration_seconds: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    sample_width: Optional[int] = None
    average_amplitude: Optional[float] = None
    peak_amplitude: Optional[float] = None
    silence_ratio: Optional[float] = None
    clipped_ratio: Optional[float] = None
    zero_crossing_rate: Optional[float] = None

    if path.suffix.lower() != ".wav":
        return {"available": False}

    with suppress(wave.Error):
        with wave.open(str(path), "rb") as audio_file:
            frames = audio_file.getnframes()
            sample_rate = audio_file.getframerate()
            channels = audio_file.getnchannels()
            sample_width = audio_file.getsampwidth()
            if sample_rate:
                duration_seconds = round(frames / float(sample_rate), 2)

            raw_frames = audio_file.readframes(min(frames, sample_rate * 10 if sample_rate else frames))
            if sample_width == 2 and raw_frames:
                values = array("h")
                values.frombytes(raw_frames)
                samples = values[::channels] if channels and channels > 1 else values

                if samples:
                    max_amplitude = float(2**15 - 1)
                    float_samples = _array_to_float_samples(samples, max_amplitude)
                    absolute = [abs(sample) for sample in float_samples]
                    average_amplitude = round(_mean(absolute), 4)
                    peak_amplitude = round(max(absolute), 4)
                    silence_ratio = round(sum(1 for sample in absolute if sample <= 0.015) / len(absolute), 4)
                    clipped_ratio = round(sum(1 for sample in absolute if sample >= 0.96) / len(absolute), 4)

                    zero_crossings = 0
                    previous = float_samples[0]
                    for current in float_samples[1:]:
                        if (previous < 0 <= current) or (previous > 0 >= current):
                            zero_crossings += 1
                        previous = current
                    zero_crossing_rate = round(zero_crossings / max(1, len(float_samples) - 1), 4)

                    pause_ratio = round(sum(1 for sample in absolute if sample <= 0.012) / len(absolute), 4)
                    amplitude_std = round(_std(absolute), 4)
                    pitch_consistency_proxy = round(clamp((0.52 if amplitude_std < 0.03 else 0.0) + (0.18 if sample_rate in {22050, 24000} else 0.0), 0.0, 1.0), 2)
                    spectrogram_texture_proxy = round(clamp((0.48 if zero_crossing_rate is not None and zero_crossing_rate < 0.01 else 0.0) + (0.16 if amplitude_std < 0.025 else 0.0), 0.0, 1.0), 2)

                    return {
                        "available": True,
                        "feature_extractor": "waveform-fallback",
                        "duration_seconds": duration_seconds,
                        "sample_rate": sample_rate,
                        "channels": channels,
                        "sample_width": sample_width,
                        "average_amplitude": average_amplitude,
                        "peak_amplitude": peak_amplitude,
                        "silence_ratio": silence_ratio,
                        "clipped_ratio": clipped_ratio,
                        "zero_crossing_rate": zero_crossing_rate,
                        "rms_mean": average_amplitude,
                        "rms_std": amplitude_std,
                        "pitch_mean_hz": None,
                        "pitch_std_hz": None,
                        "spectral_flatness_mean": None,
                        "spectral_centroid_mean": None,
                        "spectral_bandwidth_mean": None,
                        "mfcc_variability": None,
                        "mel_spectrogram_variability": None,
                        "chroma_variability": None,
                        "breathing_pause_ratio": pause_ratio,
                        "breathing_proxy": round(clamp(pause_ratio * 2.6 + amplitude_std * 1.8, 0.0, 1.0), 2),
                        "pitch_consistency_proxy": pitch_consistency_proxy,
                        "spectrogram_texture_proxy": spectrogram_texture_proxy,
                        "background_noise_proxy": round(clamp((0.52 if average_amplitude is not None and average_amplitude < 0.02 else 0.0), 0.0, 1.0), 2),
                        "micro_pause_absence_proxy": round(clamp((0.66 if duration_seconds and duration_seconds > 2 and pause_ratio < 0.03 else 0.0), 0.0, 1.0), 2),
                        "robotic_tone_proxy": round(clamp(spectrogram_texture_proxy * 0.62 + pitch_consistency_proxy * 0.28, 0.0, 1.0), 2),
                        "suspicious_regions": [],
                    }

    return {"available": False}


def extract_audio_features(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    file_size = path.stat().st_size

    hasher = hashlib.sha256()
    with path.open("rb") as source:
        hasher.update(source.read(4096))

    feature_map = _load_audio_with_librosa(file_path)
    if not feature_map.get("available"):
        feature_map = _load_audio_with_wave(file_path)

    return {
        "extension": path.suffix.lower().replace(".", ""),
        "size_bytes": file_size,
        "size_mb": round(file_size / (1024 * 1024), 2),
        "hash_seed": int(hasher.hexdigest()[:8], 16),
        "filename": path.name,
        "filename_fake_terms": filename_terms(path.name, FAKE_FILENAME_TERMS),
        "filename_real_terms": filename_terms(path.name, REAL_FILENAME_TERMS),
        "feature_extractor": feature_map.get("feature_extractor", "metadata-only"),
        "duration_seconds": feature_map.get("duration_seconds"),
        "sample_rate": feature_map.get("sample_rate"),
        "channels": feature_map.get("channels"),
        "sample_width": feature_map.get("sample_width"),
        "average_amplitude": feature_map.get("average_amplitude"),
        "peak_amplitude": feature_map.get("peak_amplitude"),
        "silence_ratio": feature_map.get("silence_ratio"),
        "clipped_ratio": feature_map.get("clipped_ratio"),
        "zero_crossing_rate": feature_map.get("zero_crossing_rate"),
        "rms_mean": feature_map.get("rms_mean"),
        "rms_std": feature_map.get("rms_std"),
        "pitch_mean_hz": feature_map.get("pitch_mean_hz"),
        "pitch_std_hz": feature_map.get("pitch_std_hz"),
        "spectral_flatness_mean": feature_map.get("spectral_flatness_mean"),
        "spectral_centroid_mean": feature_map.get("spectral_centroid_mean"),
        "spectral_bandwidth_mean": feature_map.get("spectral_bandwidth_mean"),
        "mfcc_variability": feature_map.get("mfcc_variability"),
        "mel_spectrogram_variability": feature_map.get("mel_spectrogram_variability"),
        "chroma_variability": feature_map.get("chroma_variability"),
        "breathing_pause_ratio": feature_map.get("breathing_pause_ratio"),
        "breathing_proxy": feature_map.get("breathing_proxy"),
        "pitch_consistency_proxy": feature_map.get("pitch_consistency_proxy"),
        "spectrogram_texture_proxy": feature_map.get("spectrogram_texture_proxy"),
        "background_noise_proxy": feature_map.get("background_noise_proxy"),
        "micro_pause_absence_proxy": feature_map.get("micro_pause_absence_proxy"),
        "robotic_tone_proxy": feature_map.get("robotic_tone_proxy"),
        "suspicious_regions": feature_map.get("suspicious_regions", []),
    }
