"""Server-side file storage. Files are addressed by generated keys, never by user-supplied names."""
import re
import uuid
from pathlib import Path

from app.core.config import get_settings

_KEY = re.compile(r"^[a-f0-9]{32}\.(csv|xlsx|xls|parquet|pdf)$")


def new_key(ext: str) -> str:
    return f"{uuid.uuid4().hex}.{ext}"


def _path(area: str, key: str) -> Path:
    if area not in ("originals", "parquet", "reports") or not _KEY.match(key):
        raise ValueError("Invalid storage key")
    root = (get_settings().storage_dir / area).resolve()
    p = (root / key).resolve()
    if p.parent != root:  # defence in depth against traversal
        raise ValueError("Invalid storage key")
    return p


def original_path(key: str) -> Path:
    return _path("originals", key)


def parquet_path(key: str) -> Path:
    return _path("parquet", key)


def report_path(key: str) -> Path:
    return _path("reports", key)


def delete_quietly(area: str, key: str) -> None:
    try:
        _path(area, key).unlink(missing_ok=True)
    except ValueError:
        pass
