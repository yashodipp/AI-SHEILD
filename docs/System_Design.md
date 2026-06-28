# AI Shield System Design

## Architecture

AI Shield uses a modular full-stack layout:

- Frontend: static HTML, CSS, and JavaScript pages served by Flask.
- Backend API: Flask app factory with focused blueprints by domain.
- Services layer: chatbot, speech response preparation, and report generation.
- Model layer: isolated detector modules for video, voice, and news text.
- Database layer: SQLite for analysis logs, feedback, and report metadata.

## Request flow

1. User opens the dashboard or analysis workspace from the Flask-served frontend.
2. Frontend sends file or JSON requests to dedicated `/api/*` endpoints.
3. Route handlers validate input and pass work to model/service modules.
4. Analysis results are logged to SQLite.
5. PDF and CSV reports are generated and stored in `backend/runtime/reports/`.
6. Frontend renders the result card and exposes report download buttons.
7. Chat and voice assistant modules use the latest analysis context for explanations.

## Detection strategy in this scaffold

This scaffold is designed to run immediately, so the detector modules use deterministic heuristics:

- Video: file metadata and signature-based score.
- Audio: metadata, duration hints, and signature-based score.
- Text: suspicious term matching, punctuation intensity, uppercase ratio, and credibility offsets.

These files are intentionally isolated so they can be replaced with real ML inference code later without rewriting route or frontend logic.

## Storage

- SQLite database file: `backend/runtime/database/ai_shield.db`
- Uploads: `backend/runtime/uploads/`
- Generated reports: `backend/runtime/reports/`

## Frontend modules

- `script.js`: shared component loading, form submission, result rendering, dashboard data fetch.
- `ai_agent.js`: chatbot UI and `/api/agent/chat` integration.
- `voice_agent.js`: browser speech recognition, `/api/voice-agent/respond`, and speech synthesis.
- `report.js`: report button rendering and recent report list.
- `feedback.js`: feedback form submission.

## Production extensions

- Add authentication and authorization around uploads and reports.
- Use object storage instead of local disk for files and generated reports.
- Add asynchronous task processing for heavier video and audio models.
- Replace heuristic modules with trained PyTorch, TensorFlow, or transformer pipelines.
- Add report signing or tamper-proof audit metadata.
