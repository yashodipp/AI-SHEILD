# AI Shield

AI Shield is a real-time media verification platform with voice, video, and fake-news detection workflows. This project now includes a complete `AI Shield - Voice Module` for real-time AI voice detection inside the existing app.

## What is implemented

### AI Shield - Voice Module

- WAV and MP3 upload support in the existing web UI
- browser microphone recording for short clips
- preprocessing with normalization, resampling, and light denoising
- MFCC, Mel spectrogram, and Chroma extraction
- CNN, LSTM, and Transformer-ready ensemble inference design
- explainable output with breathing, pitch, pause, waveform, and spectrogram reasons
- Flask and FastAPI endpoints for real-time deployment
- training script for ASVspoof and Fake-or-Real style datasets
- sample voice clips for smoke testing

Example voice output:

```json
{
  "prediction": "FAKE",
  "confidence": 0.93,
  "content_type": "audio",
  "reasons": [
    "No clear natural breathing pattern was detected in the clip.",
    "Pitch stayed unusually consistent, which is common in synthetic speech."
  ]
}
```

### Real-time fake-news system

- Hybrid news detector with transformer-ready inference and deterministic fallback scoring
- Clickbait, emotional tone, and misleading-language analysis
- URL/domain credibility scoring with HTTPS, trustlist/watchlist, and domain-age signals
- Fact cross-verification using the live-news lookup service
- Image verification using metadata-first analysis and caption-aware risk scoring
- Explanation blocks for why a result was classified as real or fake

### Video detection

- Short-form deepfake video analysis with explainable suspicious segment output
- Upload and URL-based video checks
- YouTube/Shorts URL checks use a fast conservative source-level mode by default to avoid slow downloads and false positives from platform compression

### Full-stack UI

- Existing AI Shield frontend remains intact
- `Analyze` page includes fake-news, video, and upgraded voice analysis
- Audio result cards show prediction, confidence, signal breakdown, and suspicious regions

### Persistence and reporting

- SQLite logging for analysis history and generated reports
- Optional MongoDB persistence for analysis records when `MONGO_URI` is configured
- CSV and PDF reports generated automatically after each analysis
- Generated runtime data is isolated under `backend/runtime/` so code folders stay clean

## Project structure

```text
AI-Shield/
├── backend/
│   ├── app.py
│   ├── fastapi_app.py
│   ├── config.py
│   ├── ml/
│   │   ├── train_fake_news_model.py
│   │   └── train_voice_model.py
│   ├── routes/
│   │   ├── news_routes.py
│   │   ├── video_routes.py
│   │   └── voice_routes.py
│   ├── services/
│   ├── models/
│   ├── utils/
│   ├── database/
│   ├── voice_module/
│   │   ├── inference.py
│   │   ├── preprocessing.py
│   │   ├── explainability.py
│   │   ├── modeling.py
│   │   └── artifacts/voice_model_manifest.json
│   ├── data/
│   │   └── source_reputation.json
│   └── runtime/
│       ├── database/
│       ├── reports/
│       └── uploads/
├── dataset/
│   ├── fake_news_dataset.csv
│   ├── voice_dataset_manifest.csv
│   ├── voice_dataset_README.md
│   └── voice_samples/
├── docs/
│   └── Voice_Module_Architecture.md
├── frontend/
│   └── upload.html
└── tests/
```

## Setup

```bash
cd "/Users/yashodip/Documents/New project/AI-Shield"
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

## Run options

### Option 1: Existing Flask app with full UI

```bash
python3 backend/app.py
```

Open: `http://127.0.0.1:5000`

### Option 2: FastAPI backend

```bash
uvicorn backend.fastapi_app:app --reload
```

Open API docs: `http://127.0.0.1:8000/docs`

## Key API endpoints

### Flask routes

- `POST /api/voice/analyze`
- `POST /api/video/analyze`
- `POST /api/news/analyze`
- `POST /api/news/analyze-url`
- `POST /api/news/analyze-image`

### FastAPI routes

- `GET /api/v2/health`
- `POST /api/v2/voice/analyze`
- `POST /api/v2/audio/analyze`
- `POST /api/v2/news/analyze-text`
- `POST /api/v2/news/analyze-url`
- `POST /api/v2/news/analyze-image`

## Voice training

Train the shipped baseline artifact from a CSV manifest:

```bash
python3 backend/ml/train_voice_model.py --manifest dataset/voice_dataset_manifest.csv
```

Recommended dataset sources:

- ASVspoof
- Fake-or-Real (FoR)

The manifest expects:

- `path`
- `label`
- `source`

## Sample audio files

- `dataset/voice_samples/real_human_style.wav`
- `dataset/voice_samples/synthetic_style.wav`

## Notes on production use

- Replace `backend/voice_module/artifacts/voice_model_manifest.json` with a retrained artifact for stronger deployment accuracy.
- Keep speaker identities disjoint across train, validation, and test splits.
- Use 2 to 10 second clips for low-latency real-time inference.
- Runtime outputs now live in `backend/runtime/database`, `backend/runtime/reports`, and `backend/runtime/uploads`.
- For slower frame-level analysis of YouTube/Shorts links, set `AI_SHIELD_ANALYZE_STREAMING_VIDEO=true`; direct video uploads and direct MP4 links still use video forensics by default.
