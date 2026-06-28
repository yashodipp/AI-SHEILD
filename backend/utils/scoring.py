from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable


FAKE_FILENAME_TERMS = {
    "ai",
    "aivoicegenerator",
    "clone",
    "cloned",
    "deepfake",
    "faceswap",
    "fake",
    "generated",
    "generator",
    "synthetic",
    "tts",
    "voicemaker",
}

REAL_FILENAME_TERMS = {
    "authentic",
    "camera",
    "genuine",
    "live",
    "official",
    "original",
    "real",
    "recording",
    "verified",
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def calibrated_confidence(
    probability: float,
    threshold: float,
    support_score: float,
    contradiction_score: float = 0.0,
    *,
    floor: float = 0.55,
    ceiling: float = 0.99,
    base: float = 0.6,
    precision: int = 2,
) -> float:
    side_span = threshold if probability < threshold else (1.0 - threshold)
    normalized_margin = 1.0 if side_span <= 0 else clamp(abs(probability - threshold) / side_span, 0.0, 1.0)
    support_score = clamp(support_score, 0.0, 1.0)
    contradiction_score = clamp(contradiction_score, 0.0, 1.0)

    confidence = (
        base
        + normalized_margin * 0.22
        + support_score * 0.3
        - contradiction_score * 0.14
    )

    if normalized_margin >= 0.3 and support_score >= 0.4:
        confidence += 0.06
    if normalized_margin >= 0.5 and support_score >= 0.55:
        confidence += 0.09

    return round(min(ceiling, max(floor, confidence)), precision)


def filename_terms(filename: str, candidates: Iterable[str]) -> list[str]:
    lowered = Path(filename).stem.lower()
    normalized = lowered.replace("-", " ").replace("_", " ")
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    return sorted(term for term in candidates if term in normalized or term in tokens)
