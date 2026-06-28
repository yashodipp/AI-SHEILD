from __future__ import annotations

import json
import sqlite3
from typing import Any


def store_analysis_log(database_path: str, record: dict[str, Any]) -> None:
    with sqlite3.connect(database_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO analysis_logs (
                id,
                analysis_type,
                input_name,
                status,
                fake_probability,
                real_probability,
                confidence,
                summary,
                metadata_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["analysis_type"],
                record["input_name"],
                record["status"],
                record["fake_probability"],
                record["real_probability"],
                record["confidence"],
                record["summary"],
                json.dumps(record.get("metadata", {}), ensure_ascii=False),
                record["created_at"],
            ),
        )
        connection.commit()


def list_recent_analyses(database_path: str, limit: int = 10) -> list[dict[str, Any]]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM analysis_logs
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    analyses: list[dict[str, Any]] = []
    for row in rows:
        analyses.append(
            {
                "id": row["id"],
                "analysis_type": row["analysis_type"],
                "input_name": row["input_name"],
                "status": row["status"],
                "fake_probability": row["fake_probability"],
                "real_probability": row["real_probability"],
                "confidence": row["confidence"],
                "summary": row["summary"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
        )
    return analyses


def summarize_analyses(database_path: str) -> dict[str, int]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_analyses,
                SUM(CASE WHEN status = 'Fake' THEN 1 ELSE 0 END) AS fake_count,
                SUM(CASE WHEN status = 'Real' THEN 1 ELSE 0 END) AS real_count
            FROM analysis_logs
            """
        )
        row = cursor.fetchone()

    return {
        "total_analyses": int(row["total_analyses"] or 0),
        "fake_count": int(row["fake_count"] or 0),
        "real_count": int(row["real_count"] or 0),
    }
