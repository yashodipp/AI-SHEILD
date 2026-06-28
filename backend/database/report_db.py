from __future__ import annotations

import sqlite3
from typing import Any
from typing import Optional


def store_report_metadata(database_path: str, record: dict[str, Any]) -> None:
    with sqlite3.connect(database_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO reports (
                id,
                analysis_id,
                report_name,
                analysis_type,
                pdf_path,
                csv_path,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["analysis_id"],
                record["report_name"],
                record["analysis_type"],
                record["pdf_path"],
                record["csv_path"],
                record["created_at"],
            ),
        )
        connection.commit()


def get_report(database_path: str, report_id: str) -> Optional[dict[str, Any]]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def list_recent_reports(database_path: str, limit: int = 10) -> list[dict[str, Any]]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM reports
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def count_reports(database_path: str) -> int:
    with sqlite3.connect(database_path) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM reports")
        row = cursor.fetchone()

    return int(row[0] or 0)
