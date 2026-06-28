
from __future__ import annotations

import sqlite3
from pathlib import Path


def init_db(database_path: str) -> None:
    db_path = Path(database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_logs (
                id TEXT PRIMARY KEY,
                analysis_type TEXT NOT NULL,
                input_name TEXT NOT NULL,
                status TEXT NOT NULL,
                fake_probability REAL NOT NULL,
                real_probability REAL NOT NULL,
                confidence REAL NOT NULL,
                summary TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                category TEXT NOT NULL,
                rating INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                report_name TEXT NOT NULL,
                analysis_type TEXT NOT NULL,
                pdf_path TEXT NOT NULL,
                csv_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()

