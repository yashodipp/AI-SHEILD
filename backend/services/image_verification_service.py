from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from backend.utils.scoring import clamp
from backend.utils.text_processing import extract_text_signals

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


IMAGE_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",
}
EDITING_MARKERS = (b"Photoshop", b"Canva", b"PicsArt", b"Midjourney", b"Stable Diffusion", b"Generated")
SOCIAL_MEDIA_MARKERS = (b"WhatsApp", b"Telegram", b"Instagram", b"XMP")


def detect_image_format(raw_bytes: bytes) -> str:
    for signature, image_format in IMAGE_SIGNATURES.items():
        if raw_bytes.startswith(signature):
            return image_format
    return "unknown"


def analyze_image_file(path: str, filename: str, caption: str = "") -> dict[str, Any]:
    file_path = Path(path)
    raw_bytes = file_path.read_bytes()
    image_hash = hashlib.sha256(raw_bytes).hexdigest()
    image_format = detect_image_format(raw_bytes)
    file_size_kb = round(len(raw_bytes) / 1024, 2)

    width = None
    height = None
    exif_present = b"Exif" in raw_bytes

    if Image is not None:
        try:
            with Image.open(file_path) as image:
                width, height = image.size
                exif_present = exif_present or bool(getattr(image, "getexif", lambda: {})())
                image_format = (image.format or image_format).lower()
        except Exception:
            pass

    editing_hits = [marker.decode("latin-1", "ignore") for marker in EDITING_MARKERS if marker in raw_bytes]
    social_hits = [marker.decode("latin-1", "ignore") for marker in SOCIAL_MEDIA_MARKERS if marker in raw_bytes]
    filename_lower = filename.lower()
    suspicious_filename = any(
        token in filename_lower for token in ("edited", "manipulated", "viral", "forward", "fake", "generated")
    )

    caption_signals = extract_text_signals(caption) if caption.strip() else None
    caption_risk = 0.0
    reasons = []

    if editing_hits:
        caption_risk += 0.18
        reasons.append(f"Image metadata contains editing-software markers: {', '.join(editing_hits)}.")
    if social_hits:
        caption_risk += 0.08
        reasons.append("Image appears to have been heavily redistributed through social platforms.")
    if suspicious_filename:
        caption_risk += 0.08
        reasons.append("The uploaded filename itself contains suspicious or viral-style keywords.")
    if not exif_present:
        caption_risk += 0.05
        reasons.append("No clear EXIF metadata was found, which reduces traceability.")
    if file_size_kb < 40:
        caption_risk += 0.06
        reasons.append("The image file is heavily compressed, which can hide manipulation traces.")
    if width is not None and height is not None and (width < 480 or height < 480):
        caption_risk += 0.05
        reasons.append("The image resolution is relatively low, which reduces verification confidence.")

    if caption_signals:
        caption_risk += min(
            0.24,
            len(caption_signals["suspicious_terms"]) * 0.04
            + len(caption_signals["suspicious_phrases"]) * 0.08
            + len(caption_signals["manipulation_phrases"]) * 0.06,
        )
        if caption_signals["suspicious_terms"] or caption_signals["suspicious_phrases"]:
            reasons.append("The image caption or accompanying claim contains suspicious fake-news language cues.")

    fake_probability = round(clamp(0.32 + caption_risk, 0.12, 0.94), 2)
    status = "Fake" if fake_probability >= 0.58 else "Real"

    if not reasons:
        reasons.append("No strong metadata manipulation clues were found in the submitted image.")

    reasons.append("Reverse image search can be added through an external provider, but this module currently performs metadata-first verification.")

    return {
        "status": status,
        "fake_probability": fake_probability,
        "real_probability": round(1 - fake_probability, 2),
        "confidence": round(min(0.94, 0.58 + abs(fake_probability - 0.5) * 0.7), 2),
        "reasons": reasons,
        "metadata": {
            "image_hash": image_hash,
            "format": image_format,
            "file_size_kb": file_size_kb,
            "width": width,
            "height": height,
            "exif_present": int(bool(exif_present)),
            "editing_markers": editing_hits,
            "distribution_markers": social_hits,
        },
    }
