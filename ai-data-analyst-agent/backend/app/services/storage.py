"""File storage interface with a local-disk implementation.

Files live at <STORAGE_DIR>/<user_id>/<uuid><suffix>, outside any static route. Names are always
generated; the client's filename is metadata only. Swap in S3/GridFS by implementing FileStorage.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

_SAFE_ID = re.compile(r"^[A-Za-z0-9]+$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9]+/[A-Za-z0-9_-]+(\.[a-z0-9]+)?$")


class FileStorage(Protocol):
    def new_ref(self, user_id: str, suffix: str) -> str: ...
    def path(self, ref: str) -> Path: ...
    def write_bytes(self, ref: str, data: bytes) -> str: ...
    def delete(self, ref: str) -> None: ...
    def delete_user(self, user_id: str) -> None: ...


class LocalFileStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def new_ref(self, user_id: str, suffix: str) -> str:
        if not _SAFE_ID.match(user_id):
            raise ValueError("invalid user id")
        if suffix and not re.fullmatch(r"\.[a-z0-9]+", suffix):
            raise ValueError("invalid suffix")
        return f"{user_id}/{uuid.uuid4().hex}{suffix}"

    def path(self, ref: str) -> Path:
        if not _SAFE_REF.match(ref):
            raise ValueError("invalid storage ref")
        p = (self.root / ref).resolve()
        if self.root not in p.parents:
            raise ValueError("storage ref escapes root")
        return p

    def write_bytes(self, ref: str, data: bytes) -> str:
        p = self.path(ref)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def delete(self, ref: str) -> None:
        try:
            self.path(ref).unlink(missing_ok=True)
        except ValueError:
            pass

    def delete_user(self, user_id: str) -> None:
        if not _SAFE_ID.match(user_id):
            return
        shutil.rmtree(self.root / user_id, ignore_errors=True)


_storage: LocalFileStorage | None = None


def get_storage() -> LocalFileStorage:
    global _storage
    root = get_settings().storage_dir
    if _storage is None or _storage.root != root.resolve():
        _storage = LocalFileStorage(root)
    return _storage


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
