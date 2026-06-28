from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
RUNTIME_DIR = BACKEND_DIR / "runtime"
DATABASE_DIR = RUNTIME_DIR / "database"
REPORTS_DIR = RUNTIME_DIR / "reports"
UPLOADS_DIR = RUNTIME_DIR / "uploads"
DATA_DIR = BACKEND_DIR / "data"


class Config:
    SECRET_KEY = os.getenv("AI_SHIELD_SECRET_KEY", "ai-shield-dev-secret")
    APP_NAME = "AI Shield"
    APP_ENV = os.getenv("AI_SHIELD_ENV", "development")
    DEBUG = os.getenv("AI_SHIELD_DEBUG", "true").lower() == "true"
    HOST = os.getenv("AI_SHIELD_HOST", "127.0.0.1")
    PORT = int(os.getenv("AI_SHIELD_PORT", "5000"))
    MAX_CONTENT_LENGTH = int(os.getenv("AI_SHIELD_MAX_UPLOAD_MB", "50")) * 1024 * 1024
    JSON_SORT_KEYS = False

    DATABASE_PATH = str(DATABASE_DIR / "ai_shield.db")
    FRONTEND_DIR = str(FRONTEND_DIR)
    REPORTS_DIR = str(REPORTS_DIR)
    UPLOADS_DIR = str(UPLOADS_DIR)
    RUNTIME_DIR = str(RUNTIME_DIR)
    SOURCE_REPUTATION_PATH = str(DATA_DIR / "source_reputation.json")

    NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
    NEWS_LOOKUP_DAYS = int(os.getenv("AI_SHIELD_NEWS_LOOKUP_DAYS", "7"))
    NEWS_LOOKUP_PAGE_SIZE = int(os.getenv("AI_SHIELD_NEWS_LOOKUP_PAGE_SIZE", "8"))
    URL_FETCH_TIMEOUT_SECONDS = float(os.getenv("AI_SHIELD_URL_FETCH_TIMEOUT_SECONDS", "6"))
    MONGO_URI = os.getenv("MONGO_URI", "")
    MONGO_DATABASE = os.getenv("MONGO_DATABASE", "ai_shield")
    TRANSFORMER_MODEL = os.getenv("AI_SHIELD_TRANSFORMER_MODEL", "distilroberta-base")
    TRANSFORMER_LOCAL_ONLY = os.getenv("AI_SHIELD_TRANSFORMER_LOCAL_ONLY", "false").lower() == "true"

    AI_AGENT_PROVIDER = os.getenv("AI_SHIELD_LLM_PROVIDER", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    AI_AGENT_TIMEOUT_SECONDS = float(os.getenv("AI_SHIELD_LLM_TIMEOUT_SECONDS", "12"))
    NORMALIZE_LEGACY_REPORTS = os.getenv("AI_SHIELD_NORMALIZE_LEGACY_REPORTS", "false").lower() == "true"

    ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
    ALLOWED_AUDIO_EXTENSIONS = {"wav", "mp3", "aac", "m4a", "ogg"}
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
