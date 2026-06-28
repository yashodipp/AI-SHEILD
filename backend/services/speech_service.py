from __future__ import annotations

from typing import Any
from typing import Optional

from backend.services.chatbot_service import detect_language


VOICE_MAP = {
    "en": {
        "speech_lang": "en-US",
        "voice_hints": [
            "Samantha",
            "Google UK English Female",
            "Google US English",
            "Zira",
            "Ava",
            "Karen",
        ],
        "provider_hints": ["google", "microsoft", "apple"],
        "gender": "female",
        "rate": 0.92,
        "pitch": 1.02,
    },
    "hi": {
        "speech_lang": "hi-IN",
        "voice_hints": [
            "Google हिन्दी",
            "Google Hindi",
            "Microsoft Heera",
            "Veena",
            "Lekha",
        ],
        "provider_hints": ["google", "microsoft", "apple"],
        "gender": "female",
        "rate": 0.92,
        "pitch": 1.02,
    },
}


def build_tts_config(language: Optional[str] = None) -> dict[str, Any]:
    selected_language = "hi" if language == "hi" else "en"
    voice = VOICE_MAP[selected_language]
    return {
        "lang": voice["speech_lang"],
        "voice_hints": voice["voice_hints"],
        "provider_hints": voice["provider_hints"],
        "gender": voice["gender"],
        "rate": voice["rate"],
        "pitch": voice["pitch"],
    }


def prepare_voice_response(transcript: str, reply: str, language: Optional[str] = None) -> dict[str, Any]:
    selected_language = detect_language(transcript, language)
    return {
        "transcript": transcript,
        "reply": reply,
        "language": selected_language,
        "tts": build_tts_config(selected_language),
    }
