from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import Blueprint, current_app, jsonify, request

from backend.database.log_analysis import list_recent_analyses
from backend.services.chatbot_service import generate_chat_reply
from backend.services.speech_service import build_tts_config


agent_bp = Blueprint("agent", __name__)


def prepare_chat_context(raw_context: Any) -> Dict[str, Any]:
    safe_context = dict(raw_context or {})

    try:
        recent_analyses = list_recent_analyses(current_app.config["DATABASE_PATH"], limit=5)
    except Exception:
        recent_analyses = []

    safe_context.setdefault("recent_analyses", recent_analyses)
    if not safe_context.get("latest_result") and recent_analyses:
        safe_context["latest_result"] = recent_analyses[0]
    return safe_context


def build_chat_response(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    message = (payload.get("message") or "").strip()
    if not message:
        return {"error": "Message is required."}, 400

    response = generate_chat_reply(
        message,
        context=prepare_chat_context(payload.get("context")),
        language=payload.get("language"),
        session_id=payload.get("session_id"),
    )
    response["tts"] = build_tts_config(response["language"])
    return response, 200


@agent_bp.post("/chat")
def chat():
    response, status_code = build_chat_response(request.get_json(silent=True) or {})
    return jsonify(response), status_code
