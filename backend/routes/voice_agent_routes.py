from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.routes.agent_routes import prepare_chat_context
from backend.services.chatbot_service import generate_chat_reply
from backend.services.speech_service import build_tts_config


voice_agent_bp = Blueprint("voice_agent", __name__)


@voice_agent_bp.post("/respond")
def voice_response():
    payload = request.get_json(silent=True) or {}
    transcript = (payload.get("transcript") or payload.get("message") or "").strip()
    if not transcript:
        return jsonify({"error": "Transcript is required."}), 400

    response = generate_chat_reply(
        transcript,
        context=prepare_chat_context(payload.get("context")),
        language=payload.get("language"),
        session_id=payload.get("session_id"),
    )
    response["transcript"] = transcript
    response["tts"] = build_tts_config(response["language"])
    return jsonify(response)
