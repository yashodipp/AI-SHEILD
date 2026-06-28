from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from backend.database.log_analysis import list_recent_analyses
from backend.services.news_intelligence_service import (
    analyze_news_image_input,
    analyze_news_text_input,
    analyze_news_url_input,
    persist_news_analysis,
)
from backend.utils.file_handler import allowed_file, save_upload


news_bp = Blueprint("news", __name__)


def _news_service_options() -> dict[str, object]:
    return {
        "live_api_key": current_app.config.get("NEWSAPI_KEY", ""),
        "lookback_days": int(current_app.config.get("NEWS_LOOKUP_DAYS", 7)),
        "page_size": int(current_app.config.get("NEWS_LOOKUP_PAGE_SIZE", 8)),
        "timeout_seconds": float(current_app.config.get("URL_FETCH_TIMEOUT_SECONDS", 6)),
    }


def _persist_result(result: dict[str, object]) -> dict[str, object]:
    persistence = persist_news_analysis(
        result,
        database_path=current_app.config["DATABASE_PATH"],
        reports_dir=current_app.config["REPORTS_DIR"],
        mongo_uri=current_app.config.get("MONGO_URI", ""),
        mongo_database=current_app.config.get("MONGO_DATABASE", "ai_shield"),
    )
    result["analysis_id"] = persistence["analysis_id"]
    result["created_at"] = persistence["created_at"]
    return persistence


@news_bp.post("/analyze")
def analyze_news_route():
    payload = request.get_json(silent=True) or request.form.to_dict()
    headline = (payload.get("headline") or "").strip()
    body = (payload.get("body") or payload.get("text") or "").strip()
    if not headline and not body:
        return jsonify({"error": "Headline or body text is required."}), 400

    result = analyze_news_text_input(
        headline,
        body,
        language=(payload.get("language") or "").strip() or None,
        live_api_key=str(_news_service_options()["live_api_key"]),
        lookback_days=int(_news_service_options()["lookback_days"]),
        page_size=int(_news_service_options()["page_size"]),
    )
    report = _persist_result(result)
    return jsonify(
        {
            "message": "News text analysis completed.",
            "result": result,
            "report": report["report"],
        }
    )


@news_bp.post("/analyze-url")
def analyze_news_url_route():
    payload = request.get_json(silent=True) or request.form.to_dict()
    url = (payload.get("url") or "").strip()
    if not url:
        return jsonify({"error": "URL is required."}), 400

    options = _news_service_options()
    try:
        result = analyze_news_url_input(
            url,
            language=(payload.get("language") or "").strip() or None,
            live_api_key=str(options["live_api_key"]),
            lookback_days=int(options["lookback_days"]),
            page_size=int(options["page_size"]),
            timeout_seconds=float(options["timeout_seconds"]),
        )
    except Exception as error:
        return jsonify({"error": str(error) or "AI Shield could not analyze this news URL right now."}), 400
    report = _persist_result(result)
    return jsonify(
        {
            "message": "URL analysis completed.",
            "result": result,
            "report": report["report"],
        }
    )


@news_bp.post("/analyze-image")
def analyze_news_image_route():
    image = request.files.get("image")
    if image is None or not image.filename:
        return jsonify({"error": "Image upload is required."}), 400

    if not allowed_file(image.filename, current_app.config["ALLOWED_IMAGE_EXTENSIONS"]):
        return jsonify({"error": "Unsupported image format. Use JPG, PNG, GIF, or WEBP."}), 400

    upload_info = save_upload(image, current_app.config["UPLOADS_DIR"], "news-image")
    caption = (request.form.get("caption") or "").strip()

    options = _news_service_options()
    result = analyze_news_image_input(
        upload_info["path"],
        upload_info["original_name"],
        caption=caption,
        live_api_key=str(options["live_api_key"]),
        lookback_days=int(options["lookback_days"]),
        page_size=int(options["page_size"]),
    )
    report = _persist_result(result)
    return jsonify(
        {
            "message": "Image verification completed.",
            "result": result,
            "report": report["report"],
        }
    )


@news_bp.get("/history")
def news_history():
    recent = list_recent_analyses(
        current_app.config["DATABASE_PATH"],
        limit=request.args.get("limit", default=20, type=int) or 20,
    )
    filtered = [
        item
        for item in recent
        if str(item.get("analysis_type", "")).startswith("news_") or item.get("analysis_type") == "text"
    ]
    return jsonify({"items": filtered})
