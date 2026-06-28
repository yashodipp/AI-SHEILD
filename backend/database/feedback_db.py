from __future__ import annotations

import sqlite3
from typing import Any


def store_feedback(database_path: str, record: dict[str, Any]) -> None:
    with sqlite3.connect(database_path) as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO feedback (
                id,
                name,
                email,
                category,
                rating,
                message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["name"],
                record["email"],
                record["category"],
                record["rating"],
                record["message"],
                record["created_at"],
            ),
        )
        connection.commit()


def list_feedback(database_path: str, limit: int = 20) -> list[dict[str, Any]]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT *
            FROM feedback
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    return [dict(row) for row in rows]

