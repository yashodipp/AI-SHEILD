from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request

from backend.database.log_analysis import store_analysis_log
from backend.database.report_db import store_report_metadata
from backend.models.deepfake_video_model import analyze_video
from backend.services.report_service import create_report_bundle
from backend.services.video_intelligence_service import analyze_video_url_input
from backend.utils.file_handler import allowed_file, save_upload


video_bp = Blueprint("video", __name__)


def _store_video_result(result: dict[str, object], input_name: str) -> tuple[str, str, dict[str, object]]:
    analysis_id = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    result["analysis_id"] = analysis_id
    result["input_name"] = input_name
    result["created_at"] = created_at

    store_analysis_log(
        current_app.config["DATABASE_PATH"],
        {
            "id": analysis_id,
            "analysis_type": result.get("analysis_type", "video"),
            "input_name": input_name,
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
    return analysis_id, created_at, report


@video_bp.post("/analyze")
def analyze_video_route():
    uploaded_file = request.files.get("video")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "Video file is required."}), 400

    if not allowed_file(uploaded_file.filename, current_app.config["ALLOWED_VIDEO_EXTENSIONS"]):
        return jsonify({"error": "Unsupported video format."}), 400

    stored_file = save_upload(uploaded_file, current_app.config["UPLOADS_DIR"], "video")
    result = analyze_video(stored_file["path"], stored_file["original_name"])
    _, _, report = _store_video_result(result, stored_file["original_name"])

    return jsonify(
        {
            "message": "Video analysis completed.",
            "result": result,
            "report": {
                "id": report["id"],
                "pdf_url": f"/api/reports/{report['id']}?format=pdf",
                "csv_url": f"/api/reports/{report['id']}?format=csv",
            },
        }
    )


@video_bp.post("/analyze-url")
def analyze_video_url_route():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    if not url:
        return jsonify({"error": "Video URL is required."}), 400

    try:
        result = analyze_video_url_input(
            url,
            uploads_dir=current_app.config["UPLOADS_DIR"],
            timeout_seconds=float(current_app.config.get("URL_FETCH_TIMEOUT_SECONDS", 6)),
        )
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": str(error) or "AI Shield could not analyze this video URL right now. Try a direct MP4 link or upload the video file."}), 502

    _, _, report = _store_video_result(result, url)
    return jsonify(
        {
            "message": "Video URL analysis completed.",
            "result": result,
            "report": {
                "id": report["id"],
                "pdf_url": f"/api/reports/{report['id']}?format=pdf",
                "csv_url": f"/api/reports/{report['id']}?format=csv",
            },
        }
    )
