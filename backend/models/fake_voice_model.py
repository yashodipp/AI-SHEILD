from __future__ import annotations

from backend.voice_module import analyze_voice_clip


def analyze_audio(file_path: str, original_name: str) -> dict[str, object]:
    return analyze_voice_clip(file_path, original_name)
