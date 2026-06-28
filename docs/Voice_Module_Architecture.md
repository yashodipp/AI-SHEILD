# AI Shield - Voice Module

## Pipeline

1. Audio intake accepts WAV and MP3 uploads plus browser microphone recordings.
2. Preprocessing normalizes the waveform, applies a light noise gate, resamples to 16 kHz mono, and trims to a short real-time window.
3. Feature extraction builds MFCC, Mel spectrogram, Chroma, pause maps, pitch statistics, and spectral descriptors.
4. Inference combines CNN-like spectrogram scoring, LSTM-like temporal scoring, and Transformer-like global context scoring.
5. Explainability maps the final result to concrete human-readable reasons and suspicious voice regions.

## Detection signals

- lack of breathing gaps
- over-consistent pitch contour
- limited micro-pauses
- repetitive or over-smooth spectral texture
- robotic tone proxy
- overly uniform background noise

## Deployment notes

- FastAPI and Flask can both serve the detector.
- The shipped artifact is a lightweight baseline manifest so the app works immediately.
- Replace `backend/voice_module/artifacts/voice_model_manifest.json` with a retrained artifact for production.
