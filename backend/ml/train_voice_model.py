from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.voice_module.preprocessing import preprocess_audio


FEATURE_COLUMNS = [
    "breathing_score",
    "pitch_consistency_score",
    "robotic_tone_score",
    "micro_pause_absence_score",
    "background_consistency_score",
    "spectral_smoothness_score",
    "spectral_flatness",
    "pitch_std_hz",
    "pause_ratio",
    "energy_variation",
    "spectral_bandwidth_mean",
]


def load_manifest_rows(manifest_path: Path) -> list[dict[str, str]]:
    with manifest_path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_dataset(rows: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray]:
    samples = []
    labels = []
    for row in rows:
        features = preprocess_audio(row["path"])
        vector = features["feature_vector"]
        samples.append([float(vector[column]) for column in FEATURE_COLUMNS])
        labels.append(1 if str(row["label"]).strip().lower() == "fake" else 0)
    return np.array(samples, dtype=np.float32), np.array(labels, dtype=np.int64)


def save_artifact(model: LogisticRegression, output_path: Path) -> None:
    artifact = {
        "name": "ai-shield-voice-baseline",
        "version": "1.0.0",
        "sample_rate": 16000,
        "clip_seconds": 6,
        "ensemble_weights": {"cnn": 0.34, "lstm": 0.33, "transformer": 0.33},
        "feature_weights": {
            column: round(float(weight), 6) for column, weight in zip(FEATURE_COLUMNS, model.coef_[0], strict=False)
        },
        "bias": round(float(model.intercept_[0]), 6),
        "threshold": 0.5,
    }
    output_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the AI Shield voice detector baseline artifact.")
    parser.add_argument("--manifest", required=True, help="CSV file with path,label,source columns.")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "backend" / "voice_module" / "artifacts" / "voice_model_manifest.json"),
        help="Where to write the trained artifact JSON.",
    )
    args = parser.parse_args()

    rows = load_manifest_rows(Path(args.manifest))
    x, y = build_dataset(rows)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, random_state=42, stratify=y)

    model = LogisticRegression(max_iter=2000)
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)

    print("Accuracy:", round(float(accuracy_score(y_test, predictions)), 4))
    print(classification_report(y_test, predictions, target_names=["real", "fake"]))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_artifact(model, output_path)
    print("Saved artifact to", output_path)


if __name__ == "__main__":
    main()
