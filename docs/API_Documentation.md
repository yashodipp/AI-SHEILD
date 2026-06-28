# AI Shield API Documentation

## Base URL

`http://127.0.0.1:5000`

FastAPI alternative:

`http://127.0.0.1:8000`

## Health

### `GET /api/health`

Returns service status.

## Dashboard

### `GET /api/dashboard/summary`

Returns recent analysis logs and lightweight counters for the dashboard.

## Video analysis

### `POST /api/video/analyze`

Accepts `multipart/form-data`.

Field:

- `video`: video file (`mp4`, `mov`, `avi`, `mkv`, `webm`)

Response includes:

- `result.status`
- `result.fake_probability`
- `result.real_probability`
- `result.confidence`
- `result.explanation`
- `report.pdf_url`
- `report.csv_url`

## Voice analysis

### `POST /api/voice/analyze`

Accepts `multipart/form-data`.

Field:

- `audio`: audio file (`wav`, `mp3`, `aac`, `m4a`, `ogg`)

## Fake news analysis

### `POST /api/news/analyze`

Accepts JSON:

```json
{
  "headline": "Paste the headline here",
  "body": "Paste article text here"
}
```

### `POST /api/news/analyze-url`

Accepts JSON:

```json
{
  "url": "https://example.com/story"
}
```

### `POST /api/news/analyze-image`

Accepts `multipart/form-data`.

Fields:

- `image`: image file (`jpg`, `jpeg`, `png`, `gif`, `webp`)
- `caption`: optional text claim attached to the image

### `GET /api/news/history`

Returns recent fake-news related analysis history.

## FastAPI fake-news endpoints

### `GET /api/v2/health`

Health check for the FastAPI service.

### `POST /api/v2/news/analyze-text`

Accepts JSON:

```json
{
  "headline": "Paste the headline here",
  "body": "Paste article text here"
}
```

### `POST /api/v2/news/analyze-url`

Accepts JSON:

```json
{
  "url": "https://example.com/story"
}
```

### `POST /api/v2/news/analyze-image`

Accepts `multipart/form-data`.

### `GET /api/v2/news/history`

Returns recent fake-news analyses logged by the FastAPI service.

### `GET /api/v2/reports/<report_id>?format=pdf|csv`

Downloads generated reports from the FastAPI flow.

## AI chatbot

### `POST /api/agent/chat`

Accepts JSON:

```json
{
  "message": "Explain my result",
  "language": "en",
  "context": {
    "latest_result": {
      "analysis_type": "text",
      "status": "Fake"
    }
  }
}
```

## Voice assistant

### `POST /api/voice-agent/respond`

Accepts JSON:

```json
{
  "transcript": "मुझे रिजल्ट समझाओ",
  "language": "hi",
  "context": {
    "latest_result": {
      "analysis_type": "video",
      "status": "Real"
    }
  }
}
```

Returns:

- `reply`
- `language`
- `tts.lang`
- `tts.rate`
- `tts.pitch`

## Feedback

### `POST /api/feedback/submit`

Accepts JSON or form data:

```json
{
  "name": "User",
  "email": "user@example.com",
  "category": "assistant",
  "rating": 4,
  "message": "Voice reply was helpful."
}
```

### `GET /api/feedback/recent`

Returns recent feedback entries.

## Reports

### `GET /api/reports/recent`

Returns recent report metadata with generated download URLs.

### `GET /api/reports/<report_id>?format=pdf`

Downloads the generated PDF.

### `GET /api/reports/<report_id>?format=csv`

Downloads the generated CSV.
