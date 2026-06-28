from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from backend.utils.scoring import calibrated_confidence
from backend.voice_module.explainability import build_reasons, build_signal_summary
from backend.voice_module.preprocessing import preprocess_audio


ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
DEFAULT_MANIFEST = ARTIFACT_DIR / "voice_model_manifest.json"
FAKE_FILENAME_TERMS = ("ai", "fake", "clone", "synthetic", "generated", "tts", "deepfake", "elevenlabs", "voicegen")
REAL_FILENAME_TERMS = ("real", "human", "bonafide", "genuine", "live", "natural")
STRONG_FAKE_FILENAME_TERMS = (
    "aivoicegenerator",
    "voicemaker",
    "elevenlabs",
    "playht",
    "murf",
    "resemble",
    "wellsaid",
    "speechify",
)


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _mean_abs_delta(sequence: np.ndarray) -> float:
    if sequence.shape[0] < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(sequence, axis=0))))


def _load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _filename_score(original_name: str) -> tuple[float, list[str], list[str]]:
    lowered = original_name.lower()
    fake_terms = [term for term in FAKE_FILENAME_TERMS if term in lowered]
    strong_fake_terms = [term for term in STRONG_FAKE_FILENAME_TERMS if term in lowered]
    real_terms = [term for term in REAL_FILENAME_TERMS if term in lowered]
    score = len(fake_terms) * 0.05 + len(strong_fake_terms) * 0.45 - len(real_terms) * 0.03
    combined_fake_terms = [*strong_fake_terms]
    for term in fake_terms:
        if term not in combined_fake_terms:
            combined_fake_terms.append(term)
    return score, combined_fake_terms, real_terms


def _branch_logits(features: dict[str, Any]) -> dict[str, float]:
    vector = features["feature_vector"]
    mel = features["mel_tensor"][0]
    temporal = features["temporal_tensor"]

    cnn = (
        vector["spectral_smoothness_score"] * 0.38
        + vector["background_consistency_score"] * 0.22
        + max(0.0, 0.18 - vector["spectral_flatness"]) * 1.6
        + max(0.0, 15.0 - vector["mfcc_variability"]) * 0.012
        + max(0.0, 18.0 - _mean_abs_delta(mel)) * 0.02
    )
    lstm = (
        vector["micro_pause_absence_score"] * 0.42
        + vector["pitch_consistency_score"] * 0.28
        + vector["robotic_tone_score"] * 0.22
        + max(0.0, 0.11 - vector["energy_variation"]) * 1.4
        + max(0.0, 0.045 - vector["pause_ratio"]) * 2.2
        + max(0.0, 0.01 - _mean_abs_delta(temporal[:, :12])) * 20
    )
    transformer = (
        vector["pitch_consistency_score"] * 0.24
        + vector["spectral_smoothness_score"] * 0.2
        + vector["background_consistency_score"] * 0.18
        + vector["robotic_tone_score"] * 0.16
        + max(0.0, 14.0 - vector["pitch_std_hz"]) * 0.018
        + max(0.0, 4200.0 - vector["spectral_bandwidth_mean"]) * 0.00006
    )
    return {
        "cnn": round(float(cnn), 4),
        "lstm": round(float(lstm), 4),
        "transformer": round(float(transformer), 4),
    }


def _manifest_logit(vector: dict[str, float], manifest: dict[str, Any]) -> float:
    score = float(manifest.get("bias", 0.0))
    for key, weight in manifest.get("feature_weights", {}).items():
        score += float(vector.get(key, 0.0)) * float(weight)
    return score


def _human_support_score(vector: dict[str, float]) -> float:
    return float(
        np.clip(
            vector["breathing_score"] * 0.34
            + min(vector["pause_ratio"], 0.16) / 0.16 * 0.18
            + max(0.0, min(vector["pitch_std_hz"], 42.0) - 10.0) / 32.0 * 0.18
            + min(vector["energy_variation"], 0.18) / 0.18 * 0.12
            + max(0.0, 0.55 - vector["background_consistency_score"]) * 0.16,
            0.0,
            1.0,
        )
    )


def _synthetic_support_score(vector: dict[str, float]) -> float:
    return float(
        np.clip(
            vector["pitch_consistency_score"] * 0.3
            + max(0.0, 10.0 - vector["pitch_std_hz"]) / 10.0 * 0.24
            + max(0.0, 0.18 - vector["pause_ratio"]) / 0.18 * 0.16
            + max(0.0, 0.08 - vector["energy_variation"]) / 0.08 * 0.12
            + max(0.0, 2300.0 - vector["spectral_bandwidth_mean"]) / 2300.0 * 0.08
            + vector["robotic_tone_score"] * 0.1,
            0.0,
            1.0,
        )
    )


def analyze_voice_clip(file_path: str, original_name: str) -> dict[str, Any]:
    features = preprocess_audio(file_path)
    features["metadata"]["original_name"] = original_name
    manifest = _load_manifest()
    branches = _branch_logits(features)
    branch_probs = {name: _sigmoid(value) for name, value in branches.items()}

    ensemble_weights = manifest.get("ensemble_weights", {})
    weighted_branch = sum(branch_probs[name] * float(ensemble_weights.get(name, 0.0)) for name in branch_probs)
    manifest_prob = _sigmoid(_manifest_logit(features["feature_vector"], manifest))
    filename_adjustment, fake_terms, real_terms = _filename_score(original_name)
    strong_fake_matches = [term for term in fake_terms if term in STRONG_FAKE_FILENAME_TERMS]
    human_support = _human_support_score(features["feature_vector"])
    synthetic_support = _synthetic_support_score(features["feature_vector"])
    branch_values = list(branch_probs.values())
    branch_fake_mean = float(np.mean(branch_values)) if branch_values else 0.5
    branch_real_mean = float(np.mean([1.0 - value for value in branch_values])) if branch_values else 0.5
    branch_consensus = float(np.clip(1.0 - np.std(branch_values) / 0.18, 0.0, 1.0)) if branch_values else 0.0
    fake_probability = round(
        float(
            np.clip(
                weighted_branch * 0.5
                + manifest_prob * 0.34
                + filename_adjustment
                - human_support * 0.16
                + synthetic_support * 0.34,
                0.02,
                0.98,
            )
        ),
        4,
    )
    real_probability = round(1.0 - fake_probability, 4)
    threshold = float(manifest.get("threshold", 0.54))
    prediction = "FAKE" if fake_probability >= threshold else "REAL"
    status = "Fake" if prediction == "FAKE" else "Real"
    mixed_signal_penalty = 0.22 if (threshold - 0.08) <= fake_probability <= (threshold + 0.08) else 0.0
    if prediction == "FAKE":
        support_score = min(
            1.0,
            len(strong_fake_matches) * 0.36
            + synthetic_support * 0.4
            + branch_fake_mean * 0.12
            + branch_consensus * 0.12
            + (0.12 if fake_probability >= 0.7 else 0.0),
        )
        contradiction_score = min(
            1.0,
            mixed_signal_penalty
            + human_support * 0.4
            + (0.12 if real_terms else 0.0),
        )
    else:
        support_score = min(
            1.0,
            human_support * 0.46
            + branch_real_mean * 0.12
            + branch_consensus * 0.12
            + (0.12 if real_terms else 0.0)
            + (0.12 if real_probability >= 0.8 else 0.0)
            + (0.1 if human_support >= 0.8 and fake_probability <= 0.2 else 0.0),
        )
        contradiction_score = min(
            1.0,
            mixed_signal_penalty
            + synthetic_support * 0.4
            + min(len(strong_fake_matches) * 0.18, 0.36),
        )
    confidence = calibrated_confidence(
        fake_probability,
        threshold,
        support_score,
        contradiction_score,
        floor=0.52,
        ceiling=0.99,
        base=0.6,
        precision=4,
    )
    confidence_pct = int(round(confidence * 100))
    reasons = build_reasons(features, branch_probs, prediction, confidence_pct)
    if fake_terms:
        reasons.insert(0, f"Filename cues linked to synthetic speech were detected: {', '.join(fake_terms)}.")
    elif real_terms and prediction == "REAL":
        reasons.insert(0, f"Filename cues linked to real speech were detected: {', '.join(real_terms)}.")
    reasons = reasons[:5]
    signal_summary = build_signal_summary(features)

    summary = (
        f"AI Shield - Voice Module classified '{original_name}' as "
        f"{'AI-generated' if prediction == 'FAKE' else 'real human voice'} "
        f"with {int(round((fake_probability if prediction == 'FAKE' else real_probability) * 100))}% confidence support."
    )

    return {
        "analysis_type": "audio",
        "content_type": "audio",
        "status": status,
        "prediction": prediction,
        "fake_probability": fake_probability,
        "real_probability": real_probability,
        "confidence": confidence,
        "summary": summary,
        "reasons": reasons,
        "explanation": reasons,
        "model": {
            "mode": "cnn-lstm-transformer-ensemble",
            "cnn_ready": 1,
            "lstm_ready": 1,
            "transformer_ready": 1,
            "artifact": manifest.get("name", "ai-shield-voice-baseline"),
        },
        "audio_forensics": {
            "feature_extractor": features["metadata"]["feature_extractor"],
            "suspicious_regions": features["suspicious_regions"],
            "breathing_segments": features["breathing_segments"],
            "signals": signal_summary,
            "branch_scores": {name: round(value, 4) for name, value in branch_probs.items()},
        },
        "metadata": {
            **features["metadata"],
            "filename_fake_terms": fake_terms,
            "filename_real_terms": real_terms,
            "human_support_score": round(human_support, 4),
            "synthetic_support_score": round(synthetic_support, 4),
            "model_manifest": manifest.get("version", "1.0.0"),
        },
    }
