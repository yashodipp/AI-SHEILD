from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from backend.database.feedback_db import list_feedback, store_feedback


feedback_bp = Blueprint("feedback", __name__)


@feedback_bp.post("/submit")
def submit_feedback():
    payload = request.get_json(silent=True) or request.form.to_dict()

    record = {
        "id": uuid4().hex,
        "name": (payload.get("name") or "Anonymous").strip(),
        "email": (payload.get("email") or "not-provided@example.com").strip(),
        "category": (payload.get("category") or "general").strip(),
        "rating": int(payload.get("rating") or 4),
        "message": (payload.get("message") or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not record["message"]:
        return jsonify({"error": "Feedback message is required."}), 400

    store_feedback(current_app.config["DATABASE_PATH"], record)
    return jsonify({"message": "Feedback submitted successfully.", "feedback": record}), 201


@feedback_bp.get("/recent")
def recent_feedback():
    records = list_feedback(current_app.config["DATABASE_PATH"])
    return jsonify({"items": records})

