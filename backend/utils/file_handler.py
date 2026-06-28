from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


def ensure_runtime_dirs(*directories: str) -> None:
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)


def allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


def save_upload(file_storage: FileStorage, upload_root: str, bucket: str) -> dict[str, str]:
    bucket_path = Path(upload_root) / bucket
    bucket_path.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(file_storage.filename or f"{bucket}.bin")
    stored_name = f"{uuid4().hex}_{safe_name}"
    destination = bucket_path / stored_name
    file_storage.save(destination)

    return {
        "original_name": safe_name,
        "stored_name": stored_name,
        "path": str(destination),
    }

