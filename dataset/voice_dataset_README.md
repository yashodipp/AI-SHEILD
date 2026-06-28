# Voice Dataset Guide

Use this manifest-driven format for training the AI Shield Voice Module.

## Recommended sources

- ASVspoof for spoofed and bonafide speech
- Fake-or-Real (FoR) for human vs synthetic speech samples

## Expected CSV columns

- `path`: absolute or project-relative path to the audio file
- `label`: `real` or `fake`
- `source`: dataset origin such as `ASVspoof` or `FoR`

## Training command

```bash
python3 backend/ml/train_voice_model.py --manifest dataset/voice_dataset_manifest.csv
```

## Notes

- Aim for 2 to 10 second clips.
- Mix speakers, microphones, rooms, and synthesis engines.
- Keep train/validation/test speaker-disjoint for real deployments.
