from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from backend.database.log_analysis import store_analysis_log
from backend.database.report_db import store_report_metadata
from backend.models.fake_voice_model import analyze_audio
from backend.services.report_service import create_report_bundle
from backend.services.voice_intelligence_service import analyze_voice_url_input
from backend.utils.file_handler import allowed_file, save_upload


voice_bp = Blueprint("voice", __name__)


def _voice_response(result: dict[str, object], report: dict[str, str]) -> object:
    return jsonify(
        {
            "message": "Audio analysis completed.",
            "prediction": result["prediction"],
            "confidence": result["confidence"],
            "content_type": result["content_type"],
            "reasons": result["reasons"],
            "result": result,
            "report": {
                "id": report["id"],
                "pdf_url": f"/api/reports/{report['id']}?format=pdf",
                "csv_url": f"/api/reports/{report['id']}?format=csv",
            },
        }
    )


@voice_bp.post("/analyze")
def analyze_voice_route():
    uploaded_file = request.files.get("audio")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "Audio file is required."}), 400

    if not allowed_file(uploaded_file.filename, current_app.config["ALLOWED_AUDIO_EXTENSIONS"]):
        return jsonify({"error": "Unsupported audio format."}), 400

    stored_file = save_upload(uploaded_file, current_app.config["UPLOADS_DIR"], "audio")
    try:
        result = analyze_audio(stored_file["path"], stored_file["original_name"])
    except Exception as error:
        return jsonify({"error": f"Voice analysis failed: {error}"}), 400

    analysis_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    result["analysis_id"] = analysis_id
    result["input_name"] = stored_file["original_name"]
    result["created_at"] = created_at

    store_analysis_log(
        current_app.config["DATABASE_PATH"],
        {
            "id": analysis_id,
            "analysis_type": "audio",
            "input_name": stored_file["original_name"],
            "status": result["status"],
            "fake_probability": result["fake_probability"],
            "real_probability": result["real_probability"],
            "confidence": result["confidence"],
            "summary": result["summary"],
            "metadata": result["metadata"],
            "created_at": created_at,
        },
    )

    report = create_report_bundle(result, current_app.config["REPORTS_DIR"])
    report["analysis_id"] = analysis_id
    store_report_metadata(current_app.config["DATABASE_PATH"], report)

    return _voice_response(result, report)


@voice_bp.post("/analyze-url")
def analyze_voice_url_route():
    payload = request.get_json(silent=True) or request.form.to_dict()
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Audio URL is required."}), 400

    try:
        result = analyze_voice_url_input(
            url,
            uploads_dir=current_app.config["UPLOADS_DIR"],
            timeout_seconds=float(current_app.config.get("URL_FETCH_TIMEOUT_SECONDS", 6)),
        )
    except Exception as error:
        return jsonify({"error": str(error) or "AI Shield could not analyze this audio URL right now. Use a direct audio link or upload the file."}), 400

    analysis_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    result["analysis_id"] = analysis_id
    result["created_at"] = created_at

    store_analysis_log(
        current_app.config["DATABASE_PATH"],
        {
            "id": analysis_id,
            "analysis_type": "audio_url",
            "input_name": url,
            "status": result["status"],
            "fake_probability": result["fake_probability"],
            "real_probability": result["real_probability"],
            "confidence": result["confidence"],
            "summary": result["summary"],
            "metadata": result["metadata"],
            "created_at": created_at,
        },
    )

    report = create_report_bundle(result, current_app.config["REPORTS_DIR"])
    report["analysis_id"] = analysis_id
    store_report_metadata(current_app.config["DATABASE_PATH"], report)
    return _voice_response(result, report)
