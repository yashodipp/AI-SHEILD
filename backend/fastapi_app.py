from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.config import Config
from backend.database.init import init_db
from backend.database.log_analysis import list_recent_analyses
from backend.database.report_db import get_report
from backend.models.deepfake_video_model import analyze_video
from backend.models.fake_voice_model import analyze_audio
from backend.services.news_intelligence_service import (
    analyze_news_image_input,
    analyze_news_text_input,
    analyze_news_url_input,
    persist_news_analysis,
)
from backend.services.report_service import (
    get_normalized_report_content,
    normalize_all_reports,
    normalize_legacy_report_file,
)
from backend.services.video_intelligence_service import analyze_video_url_input
from backend.services.voice_intelligence_service import analyze_voice_url_input
from backend.utils.file_handler import allowed_file, ensure_runtime_dirs


class TextAnalysisRequest(BaseModel):
    headline: str = ""
    body: str = ""
    language: Optional[str] = None


class UrlAnalysisRequest(BaseModel):
    url: str = Field(..., min_length=4)
    language: Optional[str] = None


class VideoUrlAnalysisRequest(BaseModel):
    url: str = Field(..., min_length=4)


class AudioUrlAnalysisRequest(BaseModel):
    url: str = Field(..., min_length=4)


app = FastAPI(title="AI Shield Fake News API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _config() -> dict[str, object]:
    return {
        "database_path": str(Path(Config.DATABASE_PATH).resolve()),
        "reports_dir": str(Path(Config.REPORTS_DIR).resolve()),
        "uploads_dir": str(Path(Config.UPLOADS_DIR).resolve()),
        "mongo_uri": Config.MONGO_URI,
        "mongo_database": Config.MONGO_DATABASE,
        "live_api_key": Config.NEWSAPI_KEY,
        "lookback_days": Config.NEWS_LOOKUP_DAYS,
        "page_size": Config.NEWS_LOOKUP_PAGE_SIZE,
        "timeout_seconds": Config.URL_FETCH_TIMEOUT_SECONDS,
    }


def _persist(result: dict[str, object]) -> dict[str, object]:
    config = _config()
    persistence = persist_news_analysis(
        result,
        database_path=str(config["database_path"]),
        reports_dir=str(config["reports_dir"]),
        mongo_uri=str(config["mongo_uri"]),
        mongo_database=str(config["mongo_database"]),
    )
    result["analysis_id"] = persistence["analysis_id"]
    result["created_at"] = persistence["created_at"]
    return persistence


def _fastapi_report_links(report_id: str) -> dict[str, str]:
    return {
        "id": report_id,
        "pdf_url": f"/api/v2/reports/{report_id}?format=pdf",
        "csv_url": f"/api/v2/reports/{report_id}?format=csv",
    }


@app.on_event("startup")
def startup() -> None:
    config = _config()
    ensure_runtime_dirs(
        str(Path(str(config["database_path"])).parent),
        str(config["reports_dir"]),
        str(config["uploads_dir"]),
        str(Path(str(config["uploads_dir"])) / "news-image"),
        str(Path(str(config["uploads_dir"])) / "video"),
        str(Path(str(config["uploads_dir"])) / "video-url"),
        str(Path(str(config["uploads_dir"])) / "audio"),
    )
    normalize_all_reports(str(config["reports_dir"]))
    init_db(str(config["database_path"]))


@app.get("/api/v2/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": Config.APP_NAME}


@app.post("/api/v2/news/analyze-text")
def analyze_text(payload: TextAnalysisRequest) -> dict[str, object]:
    config = _config()
    result = analyze_news_text_input(
        payload.headline,
        payload.body,
        language=payload.language,
        live_api_key=str(config["live_api_key"]),
        lookback_days=int(config["lookback_days"]),
        page_size=int(config["page_size"]),
    )
    persistence = _persist(result)
    return {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "result": result,
        "report": _fastapi_report_links(str(persistence["report"]["id"])),
    }


@app.post("/api/v2/news/analyze-url")
def analyze_url(payload: UrlAnalysisRequest) -> dict[str, object]:
    config = _config()
    result = analyze_news_url_input(
        payload.url,
        language=payload.language,
        live_api_key=str(config["live_api_key"]),
        lookback_days=int(config["lookback_days"]),
        page_size=int(config["page_size"]),
        timeout_seconds=float(config["timeout_seconds"]),
    )
    persistence = _persist(result)
    return {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "result": result,
        "report": _fastapi_report_links(str(persistence["report"]["id"])),
    }


@app.post("/api/v2/news/analyze-image")
def analyze_image(
    image: UploadFile = File(...),
    caption: str = Form(""),
) -> object:
    config = _config()
    if not allowed_file(image.filename or "", Config.ALLOWED_IMAGE_EXTENSIONS):
        return JSONResponse(
            status_code=400,
            content={"error": "Unsupported image format. Use JPG, PNG, GIF, or WEBP."},
        )

    image_bucket = Path(str(config["uploads_dir"])) / "news-image"
    image_bucket.mkdir(parents=True, exist_ok=True)
    destination = image_bucket / f"{uuid4().hex}_{image.filename or 'news_image.bin'}"
    destination.write_bytes(image.file.read())

    result = analyze_news_image_input(
        str(destination),
        image.filename or destination.name,
        caption=caption,
        live_api_key=str(config["live_api_key"]),
        lookback_days=int(config["lookback_days"]),
        page_size=int(config["page_size"]),
    )
    persistence = _persist(result)
    return {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "result": result,
        "report": _fastapi_report_links(str(persistence["report"]["id"])),
    }


@app.post("/api/v2/video/analyze")
def analyze_video_upload(video: UploadFile = File(...)) -> object:
    config = _config()
    if not allowed_file(video.filename or "", Config.ALLOWED_VIDEO_EXTENSIONS):
        return JSONResponse(
            status_code=400,
            content={"error": "Unsupported video format. Use MP4, MOV, AVI, MKV, or WEBM."},
        )

    bucket = Path(str(config["uploads_dir"])) / "video"
    bucket.mkdir(parents=True, exist_ok=True)
    destination = bucket / f"{uuid4().hex}_{video.filename or 'video.bin'}"
    destination.write_bytes(video.file.read())

    result = analyze_video(str(destination), video.filename or destination.name)
    result["input_name"] = video.filename or destination.name
    persistence = _persist(result)
    return {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "result": result,
        "report": _fastapi_report_links(str(persistence["report"]["id"])),
    }


@app.post("/api/v2/video/analyze-url")
def analyze_video_url(payload: VideoUrlAnalysisRequest) -> dict[str, object]:
    config = _config()
    result = analyze_video_url_input(
        payload.url,
        uploads_dir=str(config["uploads_dir"]),
        timeout_seconds=float(config["timeout_seconds"]),
    )
    persistence = _persist(result)
    return {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "result": result,
        "report": _fastapi_report_links(str(persistence["report"]["id"])),
    }


@app.post("/api/v2/audio/analyze")
@app.post("/api/v2/voice/analyze")
def analyze_audio_upload(audio: UploadFile = File(...)) -> object:
    config = _config()
    if not allowed_file(audio.filename or "", Config.ALLOWED_AUDIO_EXTENSIONS):
        return JSONResponse(
            status_code=400,
            content={"error": "Unsupported audio format. Use WAV, MP3, AAC, M4A, or OGG."},
        )

    bucket = Path(str(config["uploads_dir"])) / "audio"
    bucket.mkdir(parents=True, exist_ok=True)
    destination = bucket / f"{uuid4().hex}_{audio.filename or 'audio.bin'}"
    destination.write_bytes(audio.file.read())

    try:
        result = analyze_audio(str(destination), audio.filename or destination.name)
    except Exception as error:
        return JSONResponse(status_code=400, content={"error": f"Voice analysis failed: {error}"})
    result["input_name"] = audio.filename or destination.name
    persistence = _persist(result)
    return {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "content_type": result["content_type"],
        "reasons": result["reasons"],
        "result": result,
        "report": _fastapi_report_links(str(persistence["report"]["id"])),
    }


@app.post("/api/v2/voice/analyze-url")
def analyze_audio_url(payload: AudioUrlAnalysisRequest) -> dict[str, object]:
    config = _config()
    try:
        result = analyze_voice_url_input(
            payload.url,
            uploads_dir=str(config["uploads_dir"]),
            timeout_seconds=float(config["timeout_seconds"]),
        )
    except Exception as error:
        return JSONResponse(status_code=400, content={"error": f"Voice URL analysis failed: {error}"})
    persistence = _persist(result)
    return {
        "prediction": result["prediction"],
        "confidence": result["confidence"],
        "content_type": result["content_type"],
        "reasons": result["reasons"],
        "result": result,
        "report": _fastapi_report_links(str(persistence["report"]["id"])),
    }


@app.get("/api/v2/news/history")
def history(limit: int = 20) -> dict[str, object]:
    config = _config()
    recent = list_recent_analyses(str(config["database_path"]), limit=max(1, min(limit, 50)))
    filtered = [
        item
        for item in recent
        if str(item.get("analysis_type", "")).startswith("news_") or item.get("analysis_type") == "text"
    ]
    return {"items": filtered}


@app.get("/api/v2/reports/{report_id}")
def report_download(report_id: str, format: str = "pdf") -> object:
    report = get_report(str(_config()["database_path"]), report_id)
    if report is None:
        return JSONResponse(status_code=404, content={"error": "Report not found."})

    if format == "csv":
        path = report["csv_path"]
        media_type = "text/csv"
    else:
        path = report["pdf_path"]
        media_type = "application/pdf"

    normalize_legacy_report_file(path, format)
    content = get_normalized_report_content(path, format)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename=\"{Path(path).name}\"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
