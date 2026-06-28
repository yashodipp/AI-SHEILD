from __future__ import annotations

from typing import Any

try:
    from pymongo import MongoClient
except Exception:  # pragma: no cover - optional dependency
    MongoClient = None


def store_mongo_analysis(
    mongo_uri: str,
    database_name: str,
    record: dict[str, Any],
    *,
    collection_name: str = "analysis_logs",
) -> bool:
    if not mongo_uri or MongoClient is None:
        return False

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
    try:
        collection = client[database_name][collection_name]
        collection.insert_one(record)
        return True
    except Exception:
        return False
    finally:
        client.close()
