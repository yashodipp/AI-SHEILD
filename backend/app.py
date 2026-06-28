from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.config import Config
from backend.database.init import init_db
from backend.database.log_analysis import list_recent_analyses, summarize_analyses
from backend.database.report_db import count_reports
from backend.routes.agent_routes import agent_bp, build_chat_response
from backend.routes.feedback_routes import feedback_bp
from backend.routes.news_routes import news_bp
from backend.routes.report_routes import report_bp
from backend.routes.video_routes import video_bp
from backend.routes.voice_agent_routes import voice_agent_bp
from backend.routes.voice_routes import voice_bp
from backend.services.report_service import normalize_all_reports
from backend.utils.file_handler import ensure_runtime_dirs


def create_app(config_override: Optional[dict] = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if config_override:
        app.config.update(config_override)

    app.config["DATABASE_PATH"] = str(Path(app.config["DATABASE_PATH"]).resolve())
    app.config["REPORTS_DIR"] = str(Path(app.config["REPORTS_DIR"]).resolve())
    app.config["UPLOADS_DIR"] = str(Path(app.config["UPLOADS_DIR"]).resolve())
    app.config["FRONTEND_DIR"] = str(Path(app.config["FRONTEND_DIR"]).resolve())

    ensure_runtime_dirs(
        str(Path(app.config["DATABASE_PATH"]).parent),
        app.config["REPORTS_DIR"],
        app.config["UPLOADS_DIR"],
        str(Path(app.config["UPLOADS_DIR"]) / "video"),
        str(Path(app.config["UPLOADS_DIR"]) / "audio"),
        str(Path(app.config["UPLOADS_DIR"]) / "news-image"),
        str(Path(app.config["UPLOADS_DIR"]) / "video-url"),
    )
    normalize_all_reports(app.config["REPORTS_DIR"])
    init_db(app.config["DATABASE_PATH"])

    app.register_blueprint(video_bp, url_prefix="/api/video")
    app.register_blueprint(voice_bp, url_prefix="/api/voice")
    app.register_blueprint(news_bp, url_prefix="/api/news")
    app.register_blueprint(feedback_bp, url_prefix="/api/feedback")
    app.register_blueprint(agent_bp, url_prefix="/api/agent")
    app.register_blueprint(voice_agent_bp, url_prefix="/api/voice-agent")
    app.register_blueprint(report_bp, url_prefix="/api/reports")

    @app.after_request
    def add_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "app": app.config["APP_NAME"]})

    @app.post("/chat")
    def direct_chat():
        response, status_code = build_chat_response(request.get_json(silent=True) or {})
        return jsonify(response), status_code

    @app.get("/api/dashboard/summary")
    def dashboard_summary():
        requested_limit = request.args.get("limit", default=6, type=int) or 6
        recent = list_recent_analyses(app.config["DATABASE_PATH"], limit=max(1, min(requested_limit, 50)))
        stats = summarize_analyses(app.config["DATABASE_PATH"])
        stats["report_count"] = count_reports(app.config["DATABASE_PATH"])
        return jsonify({"stats": stats, "recent": recent})

    @app.route("/")
    def index():
        return send_from_directory(app.config["FRONTEND_DIR"], "index.html")

    @app.route("/<path:asset_path>")
    def frontend_assets(asset_path: str):
        return send_from_directory(app.config["FRONTEND_DIR"], asset_path)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
        use_reloader=False,
    )
