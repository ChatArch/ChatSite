"""Bounded static archives and safe site paths; no optional server dependencies."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import zipfile


MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
MAX_FILES = 2000
SLUG = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z')
RESERVED = {'api', 'hosting', 'sites', 'login', 'logout', 'static', 'health', 'overleaf', 'labs'}


class HostingError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def valid_slug(slug):
    if not isinstance(slug, str) or not SLUG.fullmatch(slug) or slug in RESERVED:
        raise HostingError(400, 'Invalid site identifier')
    return slug


def safe_path(name):
    if (not isinstance(name, str) or not name or len(name) > 1024 or '\\' in name
            or '\x00' in name or ':' in name or any(ord(c) < 32 for c in name)):
        raise HostingError(400, 'Invalid static path')
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {'', '.', '..'} for p in name.split('/')):
        raise HostingError(400, 'Invalid static path')
    if any(p == '.git' or p == '.env' or p.startswith('.env.') for p in path.parts):
        raise HostingError(400, 'Source-control and secret files cannot be uploaded')
    return path


def make_archive(directory: Path) -> bytes:
    directory = Path(directory).resolve()
    if not (directory / 'index.html').is_file():
        raise HostingError(400, 'Directory must contain index.html')
    output = io.BytesIO()
    total = count = 0
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob('*')):
            if path.is_symlink():
                raise HostingError(400, 'Symbolic links cannot be uploaded')
            if not path.is_file() or path.name == '.DS_Store':
                continue
            name = str(path.relative_to(directory).as_posix())
            safe_path(name)
            total += path.stat().st_size
            count += 1
            if total > MAX_EXPANDED or count > MAX_FILES:
                raise HostingError(413, 'Static directory exceeds the upload limit')
            archive.write(path, name)
    data = output.getvalue()
    if len(data) > MAX_ARCHIVE:
        raise HostingError(413, 'Archive exceeds the upload limit')
    return data


