from __future__ import annotations

import math
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np

try:  # pragma: no cover - optional dependency
    import librosa
except Exception:  # pragma: no cover - dependency may be unavailable
    librosa = None

try:  # pragma: no cover - optional dependency
    import soundfile as sf
except Exception:  # pragma: no cover - dependency may be unavailable
    sf = None

try:  # pragma: no cover - optional dependency
    from pydub import AudioSegment
except Exception:  # pragma: no cover - dependency may be unavailable
    AudioSegment = None

try:  # pragma: no cover - optional dependency
    import audioread
except Exception:  # pragma: no cover - dependency may be unavailable
    audioread = None


TARGET_SR = 16000
CLIP_SECONDS = 4
FRAME_LENGTH = 1024
HOP_LENGTH = 256
MEL_BINS = 64
MFCC_DIM = 20
CHROMA_DIM = 12
TEMPORAL_DIM = 32
MAX_FRAMES = math.ceil((TARGET_SR * CLIP_SECONDS) / HOP_LENGTH)


def _safe_float(value: Any, digits: int = 4) -> float:
    return round(float(value), digits)


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _normalize(samples: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) or 1.0
    return (samples / peak).astype(np.float32)


def _noise_gate(samples: np.ndarray) -> np.ndarray:
    floor = float(np.percentile(np.abs(samples), 20))
    threshold = max(0.003, floor * 1.6)
    return np.where(np.abs(samples) < threshold, 0.0, samples).astype(np.float32)


def _resample(samples: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    if source_sr == target_sr or not len(samples):
        return samples.astype(np.float32)
    duration = len(samples) / float(source_sr)
    source_times = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    target_length = max(1, int(duration * target_sr))
    target_times = np.linspace(0.0, duration, num=target_length, endpoint=False)
    return np.interp(target_times, source_times, samples).astype(np.float32)


def _pad_frames(matrix: np.ndarray, target_frames: int = MAX_FRAMES) -> np.ndarray:
    current = matrix.shape[-1]
    if current == target_frames:
        return matrix.astype(np.float32)
    if current > target_frames:
        return matrix[..., :target_frames].astype(np.float32)
    pad_width = [(0, 0)] * matrix.ndim
    pad_width[-1] = (0, target_frames - current)
    return np.pad(matrix, pad_width, mode="constant").astype(np.float32)


def _frame_signal(samples: np.ndarray, frame_length: int = FRAME_LENGTH, hop_length: int = HOP_LENGTH) -> np.ndarray:
    if len(samples) < frame_length:
        samples = np.pad(samples, (0, frame_length - len(samples)))
    frames = []
    for start in range(0, max(1, len(samples) - frame_length + 1), hop_length):
        frames.append(samples[start : start + frame_length])
    if not frames:
        frames.append(np.pad(samples, (0, max(0, frame_length - len(samples)))))
    return np.stack(frames).astype(np.float32)


def _fallback_spectral_features(samples: np.ndarray, sr: int) -> dict[str, np.ndarray]:
    frames = _frame_signal(samples)
    window = np.hanning(FRAME_LENGTH).astype(np.float32)
    weighted = frames * window
    spectrum = np.abs(np.fft.rfft(weighted, axis=1)).astype(np.float32) + 1e-6
    freqs = np.fft.rfftfreq(FRAME_LENGTH, d=1.0 / sr).astype(np.float32)

    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-8)
    signs = np.sign(frames)
    zcr = np.mean(np.abs(np.diff(signs, axis=1)) > 0, axis=1).astype(np.float32)
    centroid = (spectrum * freqs).sum(axis=1) / spectrum.sum(axis=1)
    bandwidth = np.sqrt((((freqs[None, :] - centroid[:, None]) ** 2) * spectrum).sum(axis=1) / spectrum.sum(axis=1))
    flatness = np.exp(np.mean(np.log(spectrum), axis=1)) / np.mean(spectrum, axis=1)

    band_edges = np.linspace(0, spectrum.shape[1], MEL_BINS + 1, dtype=int)
    mel = np.stack(
        [spectrum[:, band_edges[index] : band_edges[index + 1]].mean(axis=1) for index in range(MEL_BINS)],
        axis=0,
    )
    mel_db = 20.0 * np.log10(mel + 1e-6)

    coeff_indices = np.arange(MEL_BINS, dtype=np.float32)
    mfcc_basis = np.stack(
        [np.cos(np.pi / MEL_BINS * (coeff_indices + 0.5) * basis_index) for basis_index in range(MFCC_DIM)],
        axis=0,
    ).astype(np.float32)
    mfcc = mfcc_basis @ mel_db

    chroma = np.zeros((CHROMA_DIM, spectrum.shape[0]), dtype=np.float32)
    for frequency_index, frequency in enumerate(freqs):
        if frequency < 40:
            continue
        midi = int(round(69 + 12 * np.log2(frequency / 440.0)))
        chroma[midi % 12] += spectrum[:, frequency_index]
    chroma /= np.maximum(chroma.sum(axis=0, keepdims=True), 1e-6)

    peak_indices = np.argmax(spectrum, axis=1)
    pitches = freqs[peak_indices]
    pitches[(pitches < 70) | (pitches > 400)] = np.nan

    return {
        "rms": rms,
        "zcr": zcr,
        "spectral_centroid": centroid.astype(np.float32),
        "spectral_bandwidth": bandwidth.astype(np.float32),
        "spectral_flatness": flatness.astype(np.float32),
        "mel_db": mel_db.astype(np.float32),
        "mfcc": mfcc.astype(np.float32),
        "chroma": chroma.astype(np.float32),
        "pitches": pitches.astype(np.float32),
    }


def _extract_breath_regions(rms: np.ndarray, samples: np.ndarray, sr: int, hop_length: int) -> tuple[list[dict[str, float]], float]:
    threshold = max(float(np.percentile(rms, 18)), 0.01)
    segments: list[dict[str, float]] = []
    start = None
    total = 0.0
    for index, value in enumerate(rms):
        if value <= threshold:
            start = index if start is None else start
            continue
        if start is None:
            continue
        duration = ((index - start) * hop_length) / float(sr)
        if 0.07 <= duration <= 0.45:
            start_second = (start * hop_length) / float(sr)
            end_second = (index * hop_length) / float(sr)
            sample_start = max(0, start * hop_length)
            sample_end = min(len(samples), index * hop_length)
            segment_samples = np.abs(samples[sample_start:sample_end])
            low_energy_ratio = float(np.mean(segment_samples <= 0.03)) if segment_samples.size else 0.0
            if low_energy_ratio >= 0.4:
                total += duration
                segments.append(
                    {
                        "start_second": _safe_float(start_second, 2),
                        "end_second": _safe_float(end_second, 2),
                        "duration_seconds": _safe_float(duration, 2),
                        "reason": "Breathing-sized pause detected.",
                    }
                )
        start = None
    return segments[:6], _safe_float(total)


def _suspicious_regions(duration: float, feature_scores: dict[str, float]) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    markers = [
        ("Pitch contour", duration * 0.28, feature_scores["pitch_consistency_score"], "Pitch stayed unusually steady."),
        ("Speech flow", duration * 0.5, feature_scores["micro_pause_absence_score"], "Natural micro-pauses were limited."),
        ("Spectrogram texture", duration * 0.7, feature_scores["spectral_smoothness_score"], "Spectral texture looked over-smoothed."),
    ]
    for label, second, score, reason in markers:
        if score >= 0.45:
            regions.append(
                {
                    "segment_label": label,
                    "estimated_second": _safe_float(second, 2),
                    "anomaly_score": _safe_float(score, 2),
                    "reason": reason,
                }
            )
    return regions


def _load_wav_without_librosa(file_path: str, target_sr: int, clip_seconds: int) -> tuple[np.ndarray, int]:
    path = Path(file_path)
    if path.suffix.lower() != ".wav":
        raise RuntimeError("Fallback audio loader currently supports WAV files only.")

    with wave.open(str(path), "rb") as audio_file:
        channels = audio_file.getnchannels()
        source_sr = audio_file.getframerate()
        sample_width = audio_file.getsampwidth()
        raw = audio_file.readframes(audio_file.getnframes())

    if sample_width != 2:
        raise RuntimeError("Fallback WAV loader supports 16-bit PCM only.")

    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    samples = _resample(samples, source_sr, target_sr)
    max_samples = int(target_sr * clip_seconds)
    samples = samples[:max_samples]
    if len(samples) < max_samples:
        samples = np.pad(samples, (0, max_samples - len(samples)))
    return samples.astype(np.float32), target_sr


def _finalize_loaded_audio(samples: np.ndarray, source_sr: int, target_sr: int, clip_seconds: int) -> tuple[np.ndarray, int]:
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    samples = samples.astype(np.float32)
    if np.max(np.abs(samples)) > 1.5:
        samples = samples / 32768.0
    samples = _resample(samples, source_sr, target_sr)
    max_samples = int(target_sr * clip_seconds)
    samples = samples[:max_samples]
    if len(samples) < max_samples:
        samples = np.pad(samples, (0, max_samples - len(samples)))
    return samples.astype(np.float32), target_sr


def _load_with_soundfile(file_path: str, target_sr: int, clip_seconds: int) -> tuple[np.ndarray, int]:
    if sf is None:
        raise RuntimeError("soundfile is not available.")
    samples, source_sr = sf.read(file_path, always_2d=False)
    return _finalize_loaded_audio(np.asarray(samples), int(source_sr), target_sr, clip_seconds)


def _load_with_pydub(file_path: str, target_sr: int, clip_seconds: int) -> tuple[np.ndarray, int]:
    if AudioSegment is None:
        raise RuntimeError("pydub is not available.")
    segment = AudioSegment.from_file(file_path)
    segment = segment.set_channels(1).set_frame_rate(target_sr).set_sample_width(2)
    samples = np.array(segment.get_array_of_samples(), dtype=np.float32) / 32768.0
    return _finalize_loaded_audio(samples, target_sr, target_sr, clip_seconds)


def _load_with_audioread(file_path: str, target_sr: int, clip_seconds: int) -> tuple[np.ndarray, int]:
    if audioread is None:
        raise RuntimeError("audioread is not available.")

    chunks: list[np.ndarray] = []
    channels = 1
    source_sr = target_sr
    with audioread.audio_open(file_path) as audio_file:
        channels = int(getattr(audio_file, "channels", 1) or 1)
        source_sr = int(getattr(audio_file, "samplerate", target_sr) or target_sr)
        for buffer in audio_file:
            chunks.append(np.frombuffer(buffer, dtype="<i2").astype(np.float32) / 32768.0)

    if not chunks:
        raise RuntimeError("audioread could not read audio frames.")

    samples = np.concatenate(chunks)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return _finalize_loaded_audio(samples, source_sr, target_sr, clip_seconds)


def _load_with_afconvert(file_path: str, target_sr: int, clip_seconds: int) -> tuple[np.ndarray, int]:
    afconvert_path = "/usr/bin/afconvert"
    if not Path(afconvert_path).exists():
        raise RuntimeError("afconvert is not available.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        temp_output = Path(handle.name)

    try:
        result = subprocess.run(
            [
                afconvert_path,
                "-f",
                "WAVE",
                "-d",
                "LEI16",
                file_path,
                str(temp_output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "unknown afconvert error").strip()
            raise RuntimeError(stderr)
        return _load_wav_without_librosa(str(temp_output), target_sr, clip_seconds)
    finally:
        temp_output.unlink(missing_ok=True)


def _load_audio_any_format(file_path: str, target_sr: int, clip_seconds: int) -> tuple[np.ndarray, int]:
    loaders = []
    if librosa is not None:
        loaders.append(("librosa", lambda: librosa.load(str(Path(file_path)), sr=target_sr, mono=True)))
    loaders.append(("soundfile", lambda: _load_with_soundfile(file_path, target_sr, clip_seconds)))
    loaders.append(("audioread", lambda: _load_with_audioread(file_path, target_sr, clip_seconds)))
    loaders.append(("wav", lambda: _load_wav_without_librosa(file_path, target_sr, clip_seconds)))
    loaders.append(("afconvert", lambda: _load_with_afconvert(file_path, target_sr, clip_seconds)))
    loaders.append(("pydub", lambda: _load_with_pydub(file_path, target_sr, clip_seconds)))

    errors: list[str] = []
    for name, loader in loaders:
        try:
            loaded = loader()
            if name == "librosa":
                samples, source_sr = loaded
                return _finalize_loaded_audio(np.asarray(samples), int(source_sr), target_sr, clip_seconds)
            return loaded
        except Exception as error:
            errors.append(f"{name}: {error}")

    raise ValueError(
        "AI Shield could not decode this audio file. Try WAV or MP3, or install the optional audio decoders. "
        + " | ".join(errors[:3])
    )


def preprocess_audio(file_path: str, target_sr: int = TARGET_SR, clip_seconds: int = CLIP_SECONDS) -> dict[str, Any]:
    path = Path(file_path)
    samples, sample_rate = _load_audio_any_format(file_path, target_sr, clip_seconds)

    if samples is None or not len(samples):
        raise ValueError("Unable to decode audio clip.")

    max_samples = int(target_sr * clip_seconds)
    samples = samples[:max_samples]
    if len(samples) < max_samples:
        samples = np.pad(samples, (0, max_samples - len(samples)))

    normalized = _normalize(samples.astype(np.float32))
    denoised = _noise_gate(normalized)
    duration_seconds = min(round(len(samples) / float(target_sr), 2), float(clip_seconds))

    used_librosa = False
    if librosa is not None:
        try:
            rms = librosa.feature.rms(y=denoised, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)[0]
            zcr = librosa.feature.zero_crossing_rate(denoised, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)[0]
            spectral_centroid = librosa.feature.spectral_centroid(y=denoised, sr=target_sr, hop_length=HOP_LENGTH)[0]
            spectral_bandwidth = librosa.feature.spectral_bandwidth(y=denoised, sr=target_sr, hop_length=HOP_LENGTH)[0]
            spectral_flatness = librosa.feature.spectral_flatness(y=denoised, hop_length=HOP_LENGTH)[0]
            mel = librosa.feature.melspectrogram(y=denoised, sr=target_sr, n_mels=MEL_BINS, hop_length=HOP_LENGTH)
            mel_db = librosa.power_to_db(mel + 1e-8)
            mfcc = librosa.feature.mfcc(y=denoised, sr=target_sr, n_mfcc=MFCC_DIM, hop_length=HOP_LENGTH)
            chroma = librosa.feature.chroma_stft(y=denoised, sr=target_sr, hop_length=HOP_LENGTH)
            pitches = librosa.yin(denoised, fmin=70, fmax=400, sr=target_sr, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)
            used_librosa = True
        except Exception:
            fallback = _fallback_spectral_features(denoised, target_sr)
            rms = fallback["rms"]
            zcr = fallback["zcr"]
            spectral_centroid = fallback["spectral_centroid"]
            spectral_bandwidth = fallback["spectral_bandwidth"]
            spectral_flatness = fallback["spectral_flatness"]
            mel_db = fallback["mel_db"]
            mfcc = fallback["mfcc"]
            chroma = fallback["chroma"]
            pitches = fallback["pitches"]
    else:
        fallback = _fallback_spectral_features(denoised, target_sr)
        rms = fallback["rms"]
        zcr = fallback["zcr"]
        spectral_centroid = fallback["spectral_centroid"]
        spectral_bandwidth = fallback["spectral_bandwidth"]
        spectral_flatness = fallback["spectral_flatness"]
        mel_db = fallback["mel_db"]
        mfcc = fallback["mfcc"]
        chroma = fallback["chroma"]
        pitches = fallback["pitches"]

    valid_pitches = pitches[np.isfinite(pitches)]
    pitch_mean = float(np.mean(valid_pitches)) if valid_pitches.size else 0.0
    pitch_std = float(np.std(valid_pitches)) if valid_pitches.size else 0.0

    pause_segments, pause_ratio = _extract_breath_regions(rms, denoised, target_sr, HOP_LENGTH)
    energy_variation = float(np.std(rms))
    absolute = np.abs(denoised)
    silence_ratio = float(np.mean(absolute <= 0.015))
    pause_count = len(pause_segments)

    breathing_score = _clip01(pause_ratio * 6.2 + min(pause_count, 6) * 0.1 + max(0.0, energy_variation - 0.03) * 1.25)
    pitch_consistency_score = 0.0
    if valid_pitches.size >= 8:
        pitch_consistency_score = _clip01(max(0.0, 18.0 - pitch_std) / 18.0 * 0.72 + (0.1 if pitch_mean > 255 else 0.0))
    micro_pause_absence_score = _clip01(
        max(0.0, 0.06 - pause_ratio) * 9.8
        + max(0.0, 2 - pause_count) * 0.16
        + (0.14 if duration_seconds >= 3 and pause_count == 0 else 0.0)
    )
    spectral_smoothness_score = _clip01(
        max(0.0, 24.0 - float(np.std(mfcc))) / 24.0 * 0.58
        + max(0.0, 0.1 - float(np.std(chroma))) / 0.1 * 0.18
        + max(0.0, 0.06 - float(np.mean(spectral_flatness))) / 0.06 * 0.16
    )
    background_consistency_score = _clip01(
        max(0.0, 0.024 - float(np.std(spectral_flatness))) / 0.024 * 0.56
        + max(0.0, 0.035 - float(np.mean(spectral_flatness))) / 0.035 * 0.18
    )
    robotic_tone_score = _clip01(
        spectral_smoothness_score * 0.42
        + pitch_consistency_score * 0.34
        + max(0.0, 0.12 - energy_variation) * 1.5
        - breathing_score * 0.18
    )

    feature_scores = {
        "breathing_score": breathing_score,
        "pitch_consistency_score": pitch_consistency_score,
        "micro_pause_absence_score": micro_pause_absence_score,
        "spectral_smoothness_score": spectral_smoothness_score,
        "background_consistency_score": background_consistency_score,
        "robotic_tone_score": robotic_tone_score,
    }

    temporal_sequence = np.vstack(
        [
            _pad_frames(mfcc, MAX_FRAMES)[:12],
            _pad_frames(chroma, MAX_FRAMES)[:8],
            _pad_frames(np.expand_dims(rms, axis=0), MAX_FRAMES)[:1],
            _pad_frames(np.expand_dims(zcr, axis=0), MAX_FRAMES)[:1],
            _pad_frames(np.expand_dims(spectral_centroid / (target_sr or 1), axis=0), MAX_FRAMES)[:1],
            _pad_frames(np.expand_dims(spectral_bandwidth / (target_sr or 1), axis=0), MAX_FRAMES)[:1],
            _pad_frames(np.expand_dims(spectral_flatness, axis=0), MAX_FRAMES)[:1],
            _pad_frames(np.expand_dims(np.nan_to_num(pitches / 400.0), axis=0), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[feature_scores["breathing_score"]]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[feature_scores["micro_pause_absence_score"]]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[feature_scores["robotic_tone_score"]]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[feature_scores["background_consistency_score"]]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[feature_scores["spectral_smoothness_score"]]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[feature_scores["pitch_consistency_score"]]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[pause_ratio]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
            _pad_frames(np.repeat(np.array([[energy_variation]], dtype=np.float32), MAX_FRAMES, axis=1), MAX_FRAMES)[:1],
        ]
    ).T.astype(np.float32)

    mel_tensor = _pad_frames(mel_db, MAX_FRAMES)[np.newaxis, :, :].astype(np.float32)
    suspicious_regions = _suspicious_regions(duration_seconds, feature_scores)

    feature_vector = {
        **{key: _safe_float(value, 4) for key, value in feature_scores.items()},
        "duration_seconds": duration_seconds,
        "pause_ratio": _safe_float(pause_ratio),
        "pitch_mean_hz": _safe_float(pitch_mean, 2),
        "pitch_std_hz": _safe_float(pitch_std, 2),
        "spectral_flatness": _safe_float(np.mean(spectral_flatness)),
        "spectral_centroid_mean": _safe_float(np.mean(spectral_centroid), 2),
        "spectral_bandwidth_mean": _safe_float(np.mean(spectral_bandwidth), 2),
        "energy_variation": _safe_float(energy_variation),
        "zero_crossing_rate": _safe_float(np.mean(zcr)),
        "average_amplitude": _safe_float(np.mean(absolute)),
        "peak_amplitude": _safe_float(np.max(absolute)),
        "silence_ratio": _safe_float(silence_ratio),
        "mfcc_variability": _safe_float(np.std(mfcc), 2),
        "mel_spectrogram_variability": _safe_float(np.std(mel_db), 2),
        "chroma_variability": _safe_float(np.std(chroma)),
    }

    return {
        "sample_rate": target_sr,
        "duration_seconds": duration_seconds,
        "normalized_audio": normalized,
        "denoised_audio": denoised,
        "mel_tensor": mel_tensor,
        "temporal_tensor": temporal_sequence,
        "mfcc": _pad_frames(mfcc, MAX_FRAMES),
        "mel_spectrogram": _pad_frames(mel_db, MAX_FRAMES),
        "chroma": _pad_frames(chroma, MAX_FRAMES),
        "breathing_segments": pause_segments,
        "suspicious_regions": suspicious_regions,
        "feature_vector": feature_vector,
        "metadata": {
            "filename": path.name,
            "extension": path.suffix.lower().replace(".", ""),
            "feature_extractor": "librosa-mfcc-mel-chroma" if used_librosa else "wav-fallback-mfcc-mel-chroma",
            "sample_rate": target_sr,
            **feature_vector,
        },
    }
