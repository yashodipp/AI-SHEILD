from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request

from backend.database.report_db import get_report, list_recent_reports
from backend.services.report_service import get_normalized_report_content, normalize_legacy_report_file


report_bp = Blueprint("report", __name__)


@report_bp.get("/recent")
def recent_reports():
    requested_limit = request.args.get("limit", default=10, type=int) or 10
    reports = list_recent_reports(
        current_app.config["DATABASE_PATH"],
        limit=max(1, min(requested_limit, 50)),
    )
    items = [
        {
            "id": report["id"],
            "analysis_id": report["analysis_id"],
            "report_name": report["report_name"],
            "analysis_type": report["analysis_type"],
            "pdf_url": f"/api/reports/{report['id']}?format=pdf",
            "csv_url": f"/api/reports/{report['id']}?format=csv",
            "created_at": report["created_at"],
        }
        for report in reports
    ]
    return jsonify({"items": items})


@report_bp.get("/<report_id>")
def download_report(report_id: str):
    file_format = (request.args.get("format") or "pdf").lower()
    report = get_report(current_app.config["DATABASE_PATH"], report_id)
    if not report:
        return jsonify({"error": "Report not found."}), 404

    if file_format not in {"pdf", "csv"}:
        return jsonify({"error": "Invalid report format."}), 400

    path_key = f"{file_format}_path"
    file_path = Path(report[path_key])
    if not file_path.exists():
        return jsonify({"error": "Report file is missing on disk."}), 404

    normalize_legacy_report_file(str(file_path), file_format)
    content = get_normalized_report_content(str(file_path), file_format)

    mimetype = "application/pdf" if file_format == "pdf" else "text/csv"
    download_name = f"{report['report_name']}.{file_format}"
    response = Response(content, mimetype=mimetype)
    response.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
