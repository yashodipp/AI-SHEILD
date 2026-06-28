from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = PROJECT_ROOT / "dataset" / "fake_news_dataset.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "backend" / "ml" / "baseline_model_manifest.json"


def load_dataset(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            text = (row.get("text") or "").strip()
            label = (row.get("label") or "").strip().lower()
            if text and label in {"fake", "real"}:
                rows.append({"text": text, "label": label})
    return rows


def train_baseline(rows: list[dict[str, str]], output_path: Path) -> dict[str, Any]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import train_test_split
        from sklearn.pipeline import Pipeline
    except Exception as error:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "scikit-learn is required for baseline training. Install backend/requirements.txt first."
        ) from error

    texts = [row["text"] for row in rows]
    labels = [row["label"] for row in rows]
    x_train, x_test, y_train, y_test = train_test_split(
        texts,
        labels,
        test_size=0.2,
        random_state=42,
        stratify=labels,
    )

    model = Pipeline(
        [
            ("tfidf", TfidfVectorizer(max_features=12000, ngram_range=(1, 2))),
            ("clf", LogisticRegression(max_iter=1200)),
        ]
    )
    model.fit(x_train, y_train)
    accuracy = model.score(x_test, y_test)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "trainer": "baseline",
        "dataset_size": len(rows),
        "accuracy": round(float(accuracy), 4),
        "note": "This repository stores the training manifest only. Persist the fitted pipeline separately if needed.",
    }
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def train_transformer(rows: list[dict[str, str]], output_path: Path, model_name: str) -> dict[str, Any]:
    try:
        from datasets import Dataset
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )
    except Exception as error:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "transformers and datasets are required for transformer training. Install backend/requirements.txt first."
        ) from error

    label_map = {"real": 0, "fake": 1}
    dataset = Dataset.from_list(
        [{"text": row["text"], "label": label_map[row["label"]]} for row in rows]
    ).train_test_split(test_size=0.2, seed=42)

    tokenizer = AutoTokenizer.from_pretrained(model_name)

    def tokenize(batch: dict[str, Any]) -> dict[str, Any]:
        return tokenizer(batch["text"], truncation=True, padding="max_length", max_length=256)

    tokenized = dataset.map(tokenize, batched=True)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2)

    output_dir = output_path.parent / "transformer-output"
    args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=4,
        per_device_eval_batch_size=4,
        num_train_epochs=1,
        learning_rate=2e-5,
        evaluation_strategy="epoch",
        save_strategy="no",
        logging_steps=10,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["test"],
        tokenizer=tokenizer,
    )
    trainer.train()
    metrics = trainer.evaluate()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "trainer": "transformer",
        "model_name": model_name,
        "dataset_size": len(rows),
        "eval_metrics": metrics,
        "weights_path": str(output_dir),
    }
    output_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Train AI Shield fake-news models.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", choices=("baseline", "transformer"), default="baseline")
    parser.add_argument("--model-name", default="distilroberta-base")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    rows = load_dataset(dataset_path)
    if len(rows) < 20:
        raise RuntimeError("Dataset is too small to train a meaningful model.")

    output_path = Path(args.output)
    if args.mode == "transformer":
        manifest = train_transformer(rows, output_path, args.model_name)
    else:
        manifest = train_baseline(rows, output_path)

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
