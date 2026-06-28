from __future__ import annotations

from typing import Any


def build_reasons(features: dict[str, Any], branch_scores: dict[str, float], prediction: str, confidence_pct: int) -> list[str]:
    vector = features["feature_vector"]
    reasons: list[str] = []

    if prediction == "FAKE":
        if vector["breathing_score"] < 0.3:
            reasons.append("No clear natural breathing pattern was detected in the clip.")
        if vector["pitch_consistency_score"] >= 0.45:
            reasons.append("Pitch stayed unusually consistent, which is common in synthetic speech.")
        if vector["micro_pause_absence_score"] >= 0.45:
            reasons.append("Speech flow contained too few micro-pauses for a natural speaker.")
        if vector["spectral_smoothness_score"] >= 0.45:
            reasons.append("Spectrogram texture appears over-smoothed and repetitive.")
        if vector["background_consistency_score"] >= 0.4:
            reasons.append("Background noise profile was too uniform across the clip.")
        if vector["robotic_tone_score"] >= 0.4:
            reasons.append("Waveform dynamics suggest a robotic or over-processed tone.")
    else:
        if vector["breathing_score"] >= 0.35:
            reasons.append("Natural breathing-style gaps were present in the speech pattern.")
        if vector["pause_ratio"] >= 0.05:
            reasons.append("Micro-pauses and timing variation look closer to human delivery.")
        if vector["pitch_std_hz"] >= 15:
            reasons.append("Pitch variation stayed within a natural human range.")
        if vector["background_consistency_score"] < 0.35:
            reasons.append("Ambient texture changed naturally instead of remaining perfectly uniform.")

    strongest_branch = max(branch_scores, key=branch_scores.get)
    reasons.append(f"{strongest_branch.upper()} branch contributed the strongest signal in this analysis.")
    reasons.append(f"AI Shield voice ensemble confidence reached {confidence_pct}% on this {features['metadata']['duration_seconds']}s clip.")

    return reasons[:5]


def build_signal_summary(features: dict[str, Any]) -> dict[str, float]:
    vector = features["feature_vector"]
    return {
        "breathing_proxy": vector["breathing_score"],
        "pitch_consistency_proxy": vector["pitch_consistency_score"],
        "spectrogram_texture_proxy": vector["spectral_smoothness_score"],
        "background_noise_proxy": vector["background_consistency_score"],
        "micro_pause_absence_proxy": vector["micro_pause_absence_score"],
        "robotic_tone_proxy": vector["robotic_tone_score"],
    }
