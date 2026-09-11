"""SQLite history for authenticated ChatSite image generations."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time


class ImageHistory:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).absolute()
        if any(p.is_symlink() for p in (self.path, *self.path.parents)):
            raise ValueError("Image history must not use a symlink path")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.path.parent.chmod(0o700)
        except PermissionError:
            pass
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            if not self.path.is_file():
                raise ValueError("Image history path is not a regular file") from None
        else:
            os.close(descriptor)
        self.path.chmod(0o600)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS generations(
                    id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    model TEXT NOT NULL,
                    size TEXT NOT NULL,
                    quality TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    bytes INTEGER NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    sha256_12 TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS generations_owner_created ON generations(owner, created_at DESC);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, *, owner: str, prompt: str, model: str, size: str, quality: str,
            filename: str, image_url: str, meta: dict) -> dict:
        now = time.time()
        record_id = secrets.token_urlsafe(18)
        options = {"model": model, "size": size, "quality": quality}
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO generations(
                    id, owner, prompt, model, size, quality, options_json, filename, image_url,
                    bytes, width, height, sha256_12, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    record_id, owner, prompt, model, size, quality,
                    json.dumps(options, ensure_ascii=False, sort_keys=True),
                    filename, image_url, int(meta["bytes"]), int(meta["width"]), int(meta["height"]),
                    str(meta["sha256_12"]), now,
                ),
            )
        return self.get(record_id, owner) or {}

    def list(self, owner: str, *, limit: int = 40, offset: int = 0) -> dict:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        with self.connection() as db:
            rows = db.execute(
                """
                SELECT id, prompt, model, size, quality, filename, image_url, bytes, width, height, sha256_12, created_at
                FROM generations WHERE owner=? ORDER BY created_at DESC LIMIT ? OFFSET ?
                """,
                (owner, limit, offset),
            ).fetchall()
            total = db.execute("SELECT count(*) FROM generations WHERE owner=?", (owner,)).fetchone()[0]
        return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset, "total": total}

    def get(self, record_id: str, owner: str) -> dict | None:
        with self.connection() as db:
            row = db.execute(
                """
                SELECT id, prompt, model, size, quality, filename, image_url, bytes, width, height, sha256_12, created_at
                FROM generations WHERE id=? AND owner=?
                """,
                (record_id, owner),
            ).fetchone()
        return dict(row) if row else None


__all__ = ["ImageHistory"]
