"""ChatSite web service with an Overleaf editor feature backed by ChatOL."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import hmac
import http.cookies
import json
import mimetypes
import os
import re
import sqlite3
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any

from chatol.client import DEFAULT_COOKIE_NAME, OverleafClient, _decode_socket_io_payload
from chatol.errors import ChatOLError, CompileError, FileOperationError, UnsupportedRouteError
from chatlogin import (
    AccessDenied,
    CallbackBackend,
    Principal,
    SessionManager,
    SQLiteSessionStore,
    StoreFull,
    require_csrf,
    safe_next,
)
from chatlogin.ui import LoginUI

SESSION_COOKIE = "chatsite_session"
MAX_JSON_BODY = 2_000_000
MAX_TEXT_BODY = 1_000_000
DEFAULT_PORT = 18082
DEFAULT_DATA_DIR = Path.home() / ".chatarch" / "chatsite"
LOGIN_ASSETS = {"login.css": "text/css; charset=utf-8", "login.js": "application/javascript; charset=utf-8"}


class WebError(Exception):
    """HTTP-safe exception returned as a JSON error."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AppConfig:
    host: str
    port: int
    data_dir: Path
    admin_email: str
    admin_password: str
    default_overleaf_base_url: str
    default_overleaf_email: str
    default_overleaf_password: str
    default_overleaf_session_cookie: str
    default_openai_model: str
    openai_api_key: str
    openai_base_url: str
    session_ttl_seconds: int
    public_url: str
    allowed_origins: frozenset[str]
    secure_cookie: bool

    @classmethod
    def from_env(cls, *, host: str | None = None, port: int | None = None, data_dir: str | None = None) -> "AppConfig":
        overlay = _read_env_file(os.getenv("CHATSITE_OVERLEAF_ENV_FILE"))
        admin_password = _secret_from_env_or_file("CHATSITE_WEB_ADMIN_PASSWORD", "CHATSITE_WEB_ADMIN_PASSWORD_FILE")
        if not admin_password:
            raise RuntimeError("CHATSITE_WEB_ADMIN_PASSWORD or CHATSITE_WEB_ADMIN_PASSWORD_FILE is required")
        public_url = _origin_url(os.getenv("CHATSITE_WEB_PUBLIC_URL") or f"http://{host or os.getenv('CHATSITE_WEB_HOST', '127.0.0.1')}:{port or os.getenv('CHATSITE_WEB_PORT', str(DEFAULT_PORT))}")
        origins = {public_url}
        for origin in (os.getenv("CHATSITE_WEB_ALLOWED_ORIGINS") or "").split(","):
            if origin.strip():
                origins.add(_origin_url(origin.strip()))
        secure = (os.getenv("CHATSITE_WEB_SECURE_COOKIE") or "").lower()
        if secure not in {"", "true", "false", "1", "0"}:
            raise RuntimeError("CHATSITE_WEB_SECURE_COOKIE must be true or false")
        return cls(
            host=host or os.getenv("CHATSITE_WEB_HOST", "127.0.0.1"),
            port=int(port or os.getenv("CHATSITE_WEB_PORT", str(DEFAULT_PORT))),
            data_dir=Path(data_dir or os.getenv("CHATSITE_WEB_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser(),
            admin_email=os.getenv("CHATSITE_WEB_ADMIN_EMAIL", "admin@example.test"),
            admin_password=admin_password,
            default_overleaf_base_url=(
                os.getenv("CHATSITE_OVERLEAF_DEFAULT_URL")
                or os.getenv("OVERLEAF_SITE_URL")
                or os.getenv("OVERLEAF_URL")
                or overlay.get("OVERLEAF_SITE_URL")
                or overlay.get("OVERLEAF_URL")
                or "http://127.0.0.1:8090"
            ),
            default_overleaf_email=(
                os.getenv("OVERLEAF_ADMIN_EMAIL") or overlay.get("OVERLEAF_ADMIN_EMAIL") or ""
            ),
            default_overleaf_password=(
                os.getenv("OVERLEAF_ADMIN_PASSWORD") or overlay.get("OVERLEAF_ADMIN_PASSWORD") or ""
            ),
            default_overleaf_session_cookie=(
                os.getenv("OVERLEAF_SESSION_COOKIE") or overlay.get("OVERLEAF_SESSION_COOKIE") or ""
            ),
            default_openai_model=(
                os.getenv("CHATSITE_WEB_OPENAI_MODEL")
                or os.getenv("OPENAI_MODEL")
                or os.getenv("OPENAI_API_MODEL")
                or "gpt-5.5"
            ),
            openai_api_key=_secret_from_env_or_file("CHATSITE_OPENAI_API_KEY", "CHATSITE_OPENAI_API_KEY_FILE")
            or os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=(os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "https://api.openai.com/v1").rstrip("/"),
            session_ttl_seconds=int(os.getenv("CHATSITE_WEB_SESSION_TTL_SECONDS", str(60 * 60 * 24 * 14))),
            public_url=public_url,
            allowed_origins=frozenset(origins),
            secure_cookie=secure in {"true", "1"} if secure else public_url.startswith("https://"),
        )


class DataStore:
    """SQLite-backed settings, sessions, and conversations."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.db_path = config.data_dir / "chatsite.sqlite3"
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init()
        self.seed_defaults()

    def init(self) -> None:
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT '',
                secret INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            -- Retained for old rows/backups only; ChatLogin auth uses auth.sqlite3.
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                model_response_id TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            """
        )
        self.conn.commit()
        self._migrate()
        with contextlib.suppress(Exception):
            self.db_path.chmod(0o600)

    def _migrate(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(conversations)").fetchall()}
        if "model_response_id" not in columns:
            self.conn.execute("ALTER TABLE conversations ADD COLUMN model_response_id TEXT")
            self.conn.commit()

    def seed_defaults(self) -> None:
        defaults = {
            "overleaf_base_url": (self.config.default_overleaf_base_url, 0),
            "overleaf_email": (self.config.default_overleaf_email, 0),
            "overleaf_password": (self.config.default_overleaf_password, 1),
            "overleaf_session_cookie": (self.config.default_overleaf_session_cookie, 1),
            "overleaf_cookie_name": (DEFAULT_COOKIE_NAME, 0),
            "openai_model": (self.config.default_openai_model, 0),
            "openai_api_key": (self.config.openai_api_key, 1),
        }
        now = time.time()
        for key, (value, secret_flag) in defaults.items():
            if value is None:
                value = ""
            existing = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if existing is None:
                self.conn.execute(
                    "INSERT INTO settings(key, value, secret, updated_at) VALUES (?, ?, ?, ?)",
                    (key, str(value), secret_flag, now),
                )
        self.conn.commit()

    def settings(self, *, include_secrets: bool = False) -> dict[str, Any]:
        rows = self.conn.execute("SELECT key, value, secret FROM settings").fetchall()
        data: dict[str, Any] = {}
        for row in rows:
            key = str(row["key"])
            value = str(row["value"])
            secret_flag = bool(row["secret"])
            if secret_flag and not include_secrets:
                data[f"{key}_configured"] = bool(value)
                continue
            data[key] = value
        return data

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed_public = {"overleaf_base_url", "overleaf_email", "overleaf_cookie_name", "openai_model"}
        allowed_secret = {"overleaf_password", "overleaf_session_cookie", "openai_api_key"}
        now = time.time()
        for key in sorted(allowed_public | allowed_secret):
            if key not in payload:
                continue
            value = payload.get(key)
            if value is None:
                continue
            if key in allowed_secret and value == "":
                continue
            self.conn.execute(
                """
                INSERT INTO settings(key, value, secret, updated_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, secret = excluded.secret, updated_at = excluded.updated_at
                """,
                (key, str(value).strip() if key != "openai_api_key" else str(value).strip(), int(key in allowed_secret), now),
            )
        for clear_key, setting_key in {
            "clear_overleaf_password": "overleaf_password",
            "clear_overleaf_session_cookie": "overleaf_session_cookie",
            "clear_openai_api_key": "openai_api_key",
        }.items():
            if payload.get(clear_key):
                self.conn.execute("UPDATE settings SET value = '', updated_at = ? WHERE key = ?", (now, setting_key))
        self.conn.commit()
        return self.settings(include_secrets=False)

    def create_conversation(self, title: str | None = None) -> dict[str, Any]:
        now = time.time()
        cid = uuid.uuid4().hex
        title = (title or "New Overleaf chat").strip()[:80] or "New Overleaf chat"
        self.conn.execute(
            "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (cid, title, now, now),
        )
        self.conn.commit()
        return {"id": cid, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT 80"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, title, created_at, updated_at, model_response_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return dict(row) if row else None

    def conversation_response_id(self, conversation_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT model_response_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        return str(row["model_response_id"]) if row and row["model_response_id"] else None

    def set_conversation_response_id(self, conversation_id: str, response_id: str | None) -> None:
        if not response_id:
            return
        self.conn.execute(
            "UPDATE conversations SET model_response_id = ?, updated_at = ? WHERE id = ?",
            (response_id, time.time(), conversation_id),
        )
        self.conn.commit()

    def add_message(self, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        now = time.time()
        if not self.get_conversation(conversation_id):
            raise WebError(HTTPStatus.NOT_FOUND, "conversation_not_found", "Conversation not found")
        self.conn.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now),
        )
        if role == "user":
            title = content.strip().replace("\n", " ")[:80] or "Overleaf chat"
            self.conn.execute(
                "UPDATE conversations SET title = CASE WHEN title = 'New Overleaf chat' THEN ? ELSE title END, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
        else:
            self.conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        self.conn.commit()
        return {"role": role, "content": content, "created_at": now}

    def messages(self, conversation_id: str, *, limit: int = 80) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT role, content, created_at FROM messages
            WHERE conversation_id = ? ORDER BY id DESC LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]


class SocketIOEditor:
    """Tiny Socket.IO 0.9 polling client for Overleaf doc edits."""

    def __init__(self, client: OverleafClient, project_id: str, *, timeout: float = 5.0) -> None:
        self.client = client
        self.project_id = project_id
        self.timeout = timeout
        self.sid = ""
        self.ack_id = 0
        self._original_timeout = client.timeout

    def __enter__(self) -> "SocketIOEditor":
        self.client.timeout = self.timeout
        handshake = self.client._request(
            "GET", f"/socket.io/1/?projectId={urllib.parse.quote(self.project_id)}&t={int(time.time() * 1000)}"
        )
        if not handshake.ok:
            raise FileOperationError(f"Socket.IO handshake failed: {handshake.status}")
        self.sid = handshake.text().split(":", 1)[0].strip()
        if not self.sid:
            raise FileOperationError("Socket.IO handshake did not return a session id")
        self._drain_until_event("joinProjectResponse", max_polls=6)
        return self

    def __exit__(self, *_exc: object) -> None:
        with contextlib.suppress(Exception):
            self._post(b"0::")
        self.client.timeout = self._original_timeout

    def join_doc(self, doc_id: str) -> tuple[str, int]:
        ack = self.emit("joinDoc", [doc_id])
        if not ack or ack[0] is not None:
            raise FileOperationError(f"joinDoc failed: {ack[0] if ack else 'no acknowledgement'}")
        raw_lines = ack[1] if len(ack) > 1 and isinstance(ack[1], list) else []
        version = int(ack[2] if len(ack) > 2 else 0)
        lines = [_decode_ws_text(str(line)) for line in raw_lines]
        return "\n".join(lines), version

    def replace_doc(self, doc_id: str, new_content: str) -> dict[str, Any]:
        old_content, version = self.join_doc(doc_id)
        op: list[dict[str, Any]] = []
        if old_content:
            op.append({"p": 0, "d": old_content})
        if new_content:
            op.append({"p": 0, "i": new_content})
        update = {"op": op, "v": version}
        self.emit("applyOtUpdate", [doc_id, update])
        return {"old_bytes": len(old_content.encode("utf-8")), "new_bytes": len(new_content.encode("utf-8")), "version": version}

    def emit(self, name: str, args: list[Any]) -> list[Any]:
        self.ack_id += 1
        packet = f"5:{self.ack_id}+::" + json.dumps({"name": name, "args": args}, ensure_ascii=False, separators=(",", ":"))
        response = self._post(packet.encode("utf-8"))
        if response.status not in {200, 204}:
            raise FileOperationError(f"Socket.IO event {name} failed: {response.status}")
        return self._wait_for_ack(self.ack_id)

    def _poll_path(self) -> str:
        return f"/socket.io/1/xhr-polling/{urllib.parse.quote(self.sid)}?projectId={urllib.parse.quote(self.project_id)}&t={int(time.time() * 1000)}"

    def _post(self, body: bytes) -> Any:
        return self.client._request("POST", self._poll_path(), body=body, headers={"Content-Type": "text/plain;charset=UTF-8"})

    def _poll_packets(self) -> list[str]:
        response = self.client._request("GET", self._poll_path())
        if not response.ok:
            return []
        return _decode_socket_io_payload(response.text())

    def _drain_until_event(self, event_name: str, *, max_polls: int) -> None:
        for _ in range(max_polls):
            packets = self._safe_poll_packets()
            if any(event_name in packet for packet in packets):
                return

    def _wait_for_ack(self, ack_id: int) -> list[Any]:
        deadline = time.time() + 20
        prefix = f"6:::{ack_id}"
        while time.time() < deadline:
            for packet in self._safe_poll_packets():
                if packet.startswith(prefix):
                    rest = packet[len(prefix) :]
                    if rest.startswith("+"):
                        return json.loads(rest[1:] or "[]")
                    return []
            time.sleep(0.1)
        raise FileOperationError(f"Timed out waiting for Socket.IO ack {ack_id}")

    def _safe_poll_packets(self) -> list[str]:
        try:
            return self._poll_packets()
        except TimeoutError:
            return []
        except OSError:
            return []


def build_overleaf_client(store: DataStore) -> OverleafClient:
    settings = store.settings(include_secrets=True)
    base_url = str(settings.get("overleaf_base_url") or "").strip().rstrip("/")
    if not base_url:
        raise WebError(HTTPStatus.BAD_REQUEST, "settings_missing", "Set an Overleaf endpoint in Settings first")
    timeout = 30.0
    session_cookie = str(settings.get("overleaf_session_cookie") or "").strip()
    cookie_name = str(settings.get("overleaf_cookie_name") or DEFAULT_COOKIE_NAME).strip() or DEFAULT_COOKIE_NAME
    if session_cookie:
        return OverleafClient.from_session_cookie(base_url, session_cookie, cookie_name=cookie_name, timeout=timeout)
    email = str(settings.get("overleaf_email") or "").strip()
    password = str(settings.get("overleaf_password") or "")
    if not email or not password:
        raise WebError(HTTPStatus.BAD_REQUEST, "settings_missing", "Set Overleaf credentials or a session cookie in Settings first")
    client = OverleafClient.from_password(base_url, email, password, timeout=timeout)
    fresh_session = client.session_cookie(cookie_name)
    if fresh_session:
        store.update_settings({"overleaf_session_cookie": fresh_session})
    return client


def list_project_files(client: OverleafClient, project_id: str) -> list[dict[str, Any]]:
    files = client.list_files(project_id)
    enriched = []
    for item in files:
        found = item
        if not found.id:
            with contextlib.suppress(Exception):
                found = client._find_project_file(project_id, item.path) or item
        data = found.to_dict()
        data["editable"] = found.type == "doc" and bool(found.id)
        enriched.append(data)
    return sorted(enriched, key=lambda row: str(row.get("path", "")))


def read_project_file(client: OverleafClient, project_id: str, remote_path: str) -> dict[str, Any]:
    normalized = _normalize_remote_path(remote_path)
    entity = client._find_project_file(project_id, normalized)
    if entity and entity.type == "doc" and entity.id:
        response = client._request("GET", f"/project/{project_id}/doc/{urllib.parse.quote(entity.id)}/download")
        if not response.ok:
            raise FileOperationError(f"Failed to download doc: {response.status}")
        return {"path": normalized, "type": entity.type, "id": entity.id, "content": response.text(), "editable": True}
    data = _read_file_from_zip(client, project_id, normalized)
    return {"path": normalized, "type": entity.type if entity else "file", "id": entity.id if entity else None, "content": data, "editable": False}


def save_project_file(client: OverleafClient, project_id: str, remote_path: str, content: str) -> dict[str, Any]:
    normalized = _normalize_remote_path(remote_path)
    if len(content.encode("utf-8")) > MAX_TEXT_BODY:
        raise WebError(HTTPStatus.BAD_REQUEST, "file_too_large", "File content is too large for the web editor")
    entity = client._find_project_file(project_id, normalized)
    if entity and entity.type == "doc" and entity.id:
        with SocketIOEditor(client, project_id) as editor:
            result = editor.replace_doc(entity.id, content)
        verify = client._request("GET", f"/project/{project_id}/doc/{urllib.parse.quote(entity.id)}/download")
        ok = verify.ok and verify.text() == content
        return {"path": normalized, "mode": "ot_replace", "verified": ok, **result}
    if entity:
        raise WebError(HTTPStatus.BAD_REQUEST, "unsupported_file_type", f"Only text docs are editable for existing files; got {entity.type}")
    if "/" in normalized:
        raise WebError(HTTPStatus.BAD_REQUEST, "nested_create_unsupported", "Creating nested files is not implemented yet")
    upload = client.upload_file(project_id, content.encode("utf-8"), normalized)
    return {"path": normalized, "mode": "upload_new", "verified": True, "upload": upload.to_dict()}


def compile_project(client: OverleafClient, store: DataStore, project_id: str) -> dict[str, Any]:
    result = client.compile_project(project_id)
    job_id = uuid.uuid4().hex
    out_dir = store.config.data_dir / "artifacts" / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for output in result.output_files:
        path = (output.path or "").lower()
        if not output.url or not (path.endswith(".pdf") or path.endswith(".log") or path.endswith(".txt")):
            continue
        safe_name = _safe_artifact_name(output.path or "output.bin")
        target = out_dir / safe_name
        target.write_bytes(client.download_compile_output(output, result))
        artifacts.append({"name": safe_name, "type": output.type, "path": output.path, "url": f"/api/artifacts/{job_id}/{urllib.parse.quote(safe_name)}"})
    return {"status": result.status, "compile": result.to_dict(), "job_id": job_id, "artifacts": artifacts}


def run_openai_chat(store: DataStore, conversation_id: str, user_text: str, context: dict[str, Any]) -> str:
    settings = store.settings(include_secrets=True)
    api_key = str(settings.get("openai_api_key") or store.config.openai_api_key or "").strip()
    if not api_key:
        return (
            "OpenAI API key is not configured yet. Add it in Settings, then ask me to edit the selected "
            "Overleaf file. The project/file APIs are still available in the editor panel."
        )
    model = str(settings.get("openai_model") or store.config.default_openai_model or "gpt-5.5")
    transcript = _conversation_text(store.messages(conversation_id, limit=18))
    current = _current_context_text(context)
    instructions = (
        "You are ChatSite Overleaf, a focused Overleaf editing assistant. Help edit LaTeX projects. "
        "Use the single `overleaf` tool when you need to list projects, list files, read a file, save a file, or compile. "
        "Prefer surgical edits, preserve user content, and report exactly what changed. "
        "Never expose passwords, cookies, tokens, or raw credentials."
    )
    prompt = f"{current}\n\nRecent conversation:\n{transcript}\n\nCurrent user request:\n{user_text}"
    tools = [_overleaf_tool_schema()]
    previous_response_id = store.conversation_response_id(conversation_id)
    first_payload: dict[str, Any] = {"model": model, "instructions": instructions, "input": prompt, "tools": tools}
    if previous_response_id:
        first_payload["previous_response_id"] = previous_response_id
    response = _responses_create(store.config.openai_base_url, api_key, first_payload)
    for _ in range(5):
        calls = _extract_function_calls(response)
        if not calls:
            final_text = _extract_output_text(response) or "Done."
            store.set_conversation_response_id(conversation_id, response.get("id"))
            return final_text
        outputs = []
        for call in calls:
            tool_result = handle_overleaf_tool(store, call.get("arguments") or {})
            outputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(tool_result, ensure_ascii=False)})
        response = _responses_create(
            store.config.openai_base_url,
            api_key,
            {"model": model, "previous_response_id": response.get("id"), "input": outputs, "tools": tools},
        )
    final_text = _extract_output_text(response) or "I used the Overleaf tool, but the model did not produce a final response."
    store.set_conversation_response_id(conversation_id, response.get("id"))
    return final_text


def handle_overleaf_tool(store: DataStore, arguments: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            return {"ok": False, "error": f"Invalid JSON arguments: {exc}"}
    action = str(arguments.get("action") or "").strip()
    try:
        client = build_overleaf_client(store)
        if action == "list_projects":
            return {"ok": True, "projects": [project.to_dict() for project in client.list_projects()]}
        if action == "list_files":
            return {"ok": True, "files": list_project_files(client, _require_arg(arguments, "project_id"))}
        if action == "read_file":
            result = read_project_file(client, _require_arg(arguments, "project_id"), _require_arg(arguments, "path"))
            if len(result.get("content", "")) > 20000:
                result["content"] = result["content"][:20000] + "\n...[truncated]"
            return {"ok": True, **result}
        if action == "save_file":
            return {"ok": True, **save_project_file(client, _require_arg(arguments, "project_id"), _require_arg(arguments, "path"), str(arguments.get("content") or ""))}
        if action == "compile_project":
            return {"ok": True, **compile_project(client, store, _require_arg(arguments, "project_id"))}
        return {"ok": False, "error": f"Unknown Overleaf action: {action}"}
    except Exception as exc:  # noqa: BLE001 - tool output should be data, not a 500
        return {"ok": False, "error": _safe_error(exc), "type": type(exc).__name__}


def _credential_binding(config: AppConfig) -> str:
    digest = hashlib.sha256()
    digest.update(config.admin_email.encode("utf-8"))
    digest.update(b"\0")
    digest.update(config.admin_password.encode("utf-8"))
    return digest.hexdigest()


def _constant_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(left.encode()).digest(), hashlib.sha256(right.encode()).digest())


@dataclass
class HubAuth:
    config: AppConfig
    sessions: SessionManager
    backend: CallbackBackend
    login_ui: LoginUI

    @classmethod
    def create(cls, config: AppConfig, *, login_ui: LoginUI | None = None) -> "HubAuth":
        binding = _credential_binding(config)

        def verify(email: str, password: str):
            if not _constant_equal(email, config.admin_email):
                return None
            if not _constant_equal(password, config.admin_password):
                return None
            return Principal(config.admin_email)

        store = SQLiteSessionStore(config.data_dir / "auth.sqlite3", max_sessions=1024)
        sessions = SessionManager(store, instance="chatsite-hub-" + binding[:16], ttl=config.session_ttl_seconds)
        ui = login_ui or LoginUI(title="ChatSite", subtitle="使用已配置的 ChatSite 账号登录后继续。", palette="indigo", guest_url=None)
        return cls(config=config, sessions=sessions, backend=CallbackBackend(verify), login_ui=ui)

    def _valid_session(self, token: str | None):
        session = self.sessions.resolve(token)
        if session is None:
            return None
        if session.principal.user_id != self.config.admin_email:
            self.sessions.revoke(token)
            return None
        return session

    def session_payload(self, token: str | None) -> dict[str, Any] | None:
        session = self._valid_session(token)
        if session is None:
            return None
        return {"authenticated": True, "email": session.principal.user_id, "csrf_token": session.csrf_token}

    def require_read(self, token: str | None) -> str:
        session = self._valid_session(token)
        if session is None:
            raise WebError(HTTPStatus.UNAUTHORIZED, "auth_required", "Login required")
        return str(session.principal.user_id)

    def require_write(self, token: str | None, csrf: str | None) -> str:
        session = self._valid_session(token)
        if session is None:
            raise WebError(HTTPStatus.UNAUTHORIZED, "auth_required", "Login required")
        try:
            require_csrf(session, csrf)
        except AccessDenied:
            raise WebError(HTTPStatus.FORBIDDEN, "bad_csrf", "Session validation failed; sign in again and retry") from None
        return str(session.principal.user_id)

    def login(self, payload: dict[str, Any], previous_token: str | None, csrf: str | None) -> tuple[dict[str, Any], str]:
        extra = set(payload) - {"email", "username", "password", "next"}
        if extra or "password" not in payload or not ({"email", "username"} & set(payload)):
            raise WebError(HTTPStatus.BAD_REQUEST, "bad_fields", "Request fields are missing or unsupported")
        email, username = payload.get("email"), payload.get("username")
        if email is not None and username is not None and email != username:
            raise WebError(HTTPStatus.BAD_REQUEST, "bad_login_alias", "Login account fields do not match")
        login_email = email if email is not None else username
        password = payload["password"]
        if not isinstance(login_email, str) or not isinstance(password, str):
            raise WebError(HTTPStatus.UNAUTHORIZED, "bad_login", "Invalid email or password")
        if payload.get("next") is not None and not isinstance(payload["next"], str):
            raise WebError(HTTPStatus.BAD_REQUEST, "bad_next", "Login redirect is invalid")
        prior = self._valid_session(previous_token)
        if prior is not None and csrf is not None:
            try:
                require_csrf(prior, csrf)
            except AccessDenied:
                raise WebError(HTTPStatus.FORBIDDEN, "bad_csrf", "Session validation failed; sign in again and retry") from None
        principal = self.backend.authenticate(login_email.strip(), password)
        if principal is None:
            raise WebError(HTTPStatus.UNAUTHORIZED, "bad_login", "Invalid email or password")
        try:
            issued = self.sessions.issue(principal, previous_token=previous_token if prior is not None else None)
        except StoreFull:
            raise WebError(HTTPStatus.SERVICE_UNAVAILABLE, "auth_store_full", "Login session storage is full; retry later") from None
        return ({
            "authenticated": True,
            "email": principal.user_id,
            "csrf_token": issued.session.csrf_token,
            "next": safe_next(payload.get("next"), default="/"),
        }, issued.token)

    def logout(self, token: str | None, csrf: str | None) -> None:
        self.require_write(token, csrf)
        self.sessions.revoke(token)

    def login_page(self, next_url: str | None = None) -> str:
        context = {
            "login_url": "/api/login",
            "session_url": "/login/session",
            "logout_url": "/api/logout",
            "assets_path": "/login/assets",
            "next": safe_next(next_url, default="/"),
        }
        return self.login_ui.render(context)


class ChatOLWebHandler(BaseHTTPRequestHandler):
    server_version = "ChatSiteOverleaf/0.1"
    config: AppConfig
    store: DataStore
    auth: HubAuth

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def _dispatch(self, method: str) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            self._check_origin(method)
            if path == "/login" and method == "GET":
                return self._login_page((urllib.parse.parse_qs(parsed.query).get("next") or [None])[0])
            if path.startswith("/login/assets/") and method == "GET":
                return self._login_asset(path.removeprefix("/login/assets/"))
            if path == "/login/session" and method == "GET":
                current = self.auth.session_payload(self._session_token())
                return self._json(200, current if current is not None else {"authenticated": False})
            if path in {"/", "/index.html"}:
                if self.auth.session_payload(self._session_token()) is None:
                    return self._redirect("/login?next=/")
                return self._send_static("index.html")
            if path in {"/overleaf", "/overleaf/", "/overleaf.html"}:
                if self.auth.session_payload(self._session_token()) is None:
                    return self._redirect("/login?next=/overleaf")
                return self._send_static("overleaf.html")
            if path.startswith("/static/"):
                return self._send_static(path.removeprefix("/static/"))
            if path == "/health":
                return self._json(200, {"ok": True, "service": "chatsite-web"})
            if path == "/api/login" and method == "POST":
                return self._login()
            if path == "/api/me":
                current = self.auth.session_payload(self._session_token())
                return self._json(200, current if current is not None else {"authenticated": False, "email": None})
            if path == "/api/session":
                current = self.auth.session_payload(self._session_token())
                if current is None:
                    raise WebError(HTTPStatus.UNAUTHORIZED, "auth_required", "Login required")
                return self._json(200, current)
            user = self._require_user(method)
            if path == "/api/logout" and method == "POST":
                return self._logout()
            if path == "/api/settings":
                if method == "GET":
                    return self._json(200, {"settings": self.store.settings(include_secrets=False)})
                if method in {"POST", "PUT"}:
                    return self._json(200, {"settings": self.store.update_settings(self._read_json())})
            if path == "/api/overleaf/test" and method == "POST":
                client = build_overleaf_client(self.store)
                return self._json(200, {"ok": True, "projects": len(client.list_projects())})
            if path == "/api/projects" and method == "GET":
                client = build_overleaf_client(self.store)
                return self._json(200, {"projects": [project.to_dict() for project in client.list_projects()]})
            if path == "/api/conversations":
                if method == "GET":
                    return self._json(200, {"conversations": self.store.list_conversations()})
                if method == "POST":
                    return self._json(201, {"conversation": self.store.create_conversation((self._read_json()).get("title"))})
            if method == "GET" and (match := re.fullmatch(r"/api/conversations/([0-9a-f]+)/messages", path)):
                cid = match.group(1)
                return self._json(200, {"messages": self.store.messages(cid)})
            if method == "POST" and (match := re.fullmatch(r"/api/conversations/([0-9a-f]+)/messages", path)):
                return self._chat(match.group(1), user)
            if method == "GET" and (match := re.fullmatch(r"/api/projects/([^/]+)/files", path)):
                client = build_overleaf_client(self.store)
                return self._json(200, {"files": list_project_files(client, urllib.parse.unquote(match.group(1)))})
            if method == "GET" and (match := re.fullmatch(r"/api/projects/([^/]+)/files/content", path)):
                query = urllib.parse.parse_qs(parsed.query)
                remote_path = (query.get("path") or [""])[0]
                client = build_overleaf_client(self.store)
                return self._json(200, {"file": read_project_file(client, urllib.parse.unquote(match.group(1)), remote_path)})
            if method in {"POST", "PUT"} and (match := re.fullmatch(r"/api/projects/([^/]+)/files/content", path)):
                body = self._read_json()
                client = build_overleaf_client(self.store)
                result = save_project_file(client, urllib.parse.unquote(match.group(1)), str(body.get("path") or ""), str(body.get("content") or ""))
                return self._json(200, {"ok": True, "result": result})
            if method == "POST" and (match := re.fullmatch(r"/api/projects/([^/]+)/compile", path)):
                client = build_overleaf_client(self.store)
                return self._json(200, compile_project(client, self.store, urllib.parse.unquote(match.group(1))))
            if method == "GET" and (match := re.fullmatch(r"/api/artifacts/([0-9a-f]+)/([^/]+)", path)):
                return self._artifact(match.group(1), urllib.parse.unquote(match.group(2)))
            raise WebError(HTTPStatus.NOT_FOUND, "not_found", f"No route for {method} {path}")
        except WebError as exc:
            self._json(exc.status, {"ok": False, "error": exc.code, "message": exc.message})
        except ChatOLError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": getattr(exc, "code", "chatol_error"), "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - HTTP server boundary
            traceback.print_exc()
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "internal_error", "message": _safe_error(exc)})

    def _login(self) -> None:
        payload = self._read_json()
        data, token = self.auth.login(payload, self._session_token(), self.headers.get("X-CSRF-Token"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", self._session_cookie(token))
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _logout(self) -> None:
        self.auth.logout(self._session_token(), self.headers.get("X-CSRF-Token"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", self._expired_session_cookie())
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def _chat(self, conversation_id: str, _user: str) -> None:
        body = self._read_json()
        content = str(body.get("content") or "").strip()
        if not content:
            raise WebError(HTTPStatus.BAD_REQUEST, "empty_message", "Message cannot be empty")
        self.store.add_message(conversation_id, "user", content)
        assistant = run_openai_chat(self.store, conversation_id, content, body.get("context") or {})
        self.store.add_message(conversation_id, "assistant", assistant)
        self._json(200, {"message": {"role": "assistant", "content": assistant, "created_at": time.time()}})

    def _artifact(self, job_id: str, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise WebError(HTTPStatus.BAD_REQUEST, "bad_artifact", "Invalid artifact name")
        path = (self.config.data_dir / "artifacts" / job_id / name).resolve()
        root = (self.config.data_dir / "artifacts" / job_id).resolve()
        if root not in path.parents or not path.exists():
            raise WebError(HTTPStatus.NOT_FOUND, "artifact_not_found", "Artifact not found")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def _send_static(self, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise WebError(HTTPStatus.NOT_FOUND, "not_found", "Static asset not found")
        try:
            ref = resources.files("chatsite").joinpath("web_static", name)
            data = ref.read_bytes()
        except FileNotFoundError as exc:
            raise WebError(HTTPStatus.NOT_FOUND, "not_found", "Static asset not found") from exc
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.endswith(".js"):
            content_type = "application/javascript"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") or content_type == "application/javascript" else content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _login_page(self, next_url: str | None) -> None:
        data = self.auth.login_page(next_url).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _login_asset(self, name: str) -> None:
        media_type = LOGIN_ASSETS.get(name)
        if media_type is None:
            raise WebError(HTTPStatus.NOT_FOUND, "not_found", "Static asset not found")
        data = resources.files("chatlogin").joinpath("web", "assets", name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length > MAX_JSON_BODY:
            raise WebError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large", "Request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WebError(HTTPStatus.BAD_REQUEST, "bad_json", "Request body must be JSON") from exc
        if not isinstance(value, dict):
            raise WebError(HTTPStatus.BAD_REQUEST, "bad_json", "Request body must be a JSON object")
        return value

    def _session_token(self) -> str | None:
        cookie = http.cookies.SimpleCookie(self.headers.get("Cookie"))
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _require_user(self, method: str) -> str:
        if method in {"GET", "HEAD", "OPTIONS"}:
            return self.auth.require_read(self._session_token())
        return self.auth.require_write(self._session_token(), self.headers.get("X-CSRF-Token"))

    def _check_origin(self, method: str) -> None:
        if method in {"GET", "HEAD", "OPTIONS"}:
            return
        origins = self.headers.get_all("Origin", [])
        origin = origins[0].rstrip("/") if len(origins) == 1 else None
        if len(origins) > 1 or (origin and origin not in self.config.allowed_origins) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise WebError(HTTPStatus.FORBIDDEN, "bad_origin", "Cross-site write request rejected")

    def _session_cookie(self, token: str) -> str:
        secure = "; Secure" if self.config.secure_cookie else ""
        return f"{SESSION_COOKIE}={token}; HttpOnly{secure}; SameSite=Lax; Path=/; Max-Age={self.config.session_ttl_seconds}"

    def _expired_session_cookie(self) -> str:
        secure = "; Secure" if self.config.secure_cookie else ""
        return f"{SESSION_COOKIE}=; HttpOnly{secure}; SameSite=Lax; Path=/; Max-Age=0"


def _read_env_file(path_value: str | None) -> dict[str, str]:
    if not path_value:
        return {}
    path = Path(path_value).expanduser()
    if not path.exists():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        key, value = stripped.split("=", 1)
        value = value.strip().strip('"').strip("'")
        data[key.strip()] = value
    return data


def _secret_from_env_or_file(env_name: str, file_env_name: str) -> str:
    if os.getenv(env_name):
        return os.getenv(env_name, "")
    path_value = os.getenv(file_env_name)
    if not path_value:
        return ""
    path = Path(path_value).expanduser()
    if not path.exists():
        return ""
    return path.read_text(errors="replace").strip()


def _origin_url(value: str) -> str:
    try:
        part = urllib.parse.urlsplit(value)
        _ = part.port
    except ValueError:
        raise RuntimeError("CHATSITE_WEB_PUBLIC_URL/ALLOWED_ORIGINS must contain valid URLs") from None
    if (
        part.scheme not in {"http", "https"}
        or not part.hostname
        or part.username
        or part.password
        or part.path not in {"", "/"}
        or part.query
        or part.fragment
        or any(char.isspace() for char in value)
    ):
        raise RuntimeError("CHATSITE_WEB_PUBLIC_URL/ALLOWED_ORIGINS must be HTTP(S) origins without credentials, path, query, or fragment")
    return value.rstrip("/")


def _normalize_remote_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/").lstrip("/")
    if not normalized or normalized.endswith("/") or "\x00" in normalized:
        raise WebError(HTTPStatus.BAD_REQUEST, "bad_path", "Remote path must name a file")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise WebError(HTTPStatus.BAD_REQUEST, "bad_path", "Remote path contains an unsafe segment")
    return normalized


def _read_file_from_zip(client: OverleafClient, project_id: str, remote_path: str) -> str:
    import zipfile
    from io import BytesIO

    data = client.download_project_zip(project_id)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        try:
            info = archive.getinfo(remote_path)
        except KeyError as exc:
            raise FileOperationError(f"File not found: {remote_path}") from exc
        content = archive.read(info)
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WebError(HTTPStatus.BAD_REQUEST, "binary_file", "This file is not UTF-8 text") from exc


def _decode_ws_text(value: str) -> str:
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def _safe_artifact_name(name: str) -> str:
    candidate = Path(name.replace("\\", "/")).name.strip() or "output.bin"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", candidate)


def _safe_error(exc: Exception) -> str:
    text = str(exc) or type(exc).__name__
    return re.sub(r"(password|token|cookie|key)=([^\s&]+)", r"\1=[REDACTED]", text, flags=re.I)[:500]


def _require_arg(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"Missing required argument: {name}")
    return value


def _overleaf_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "name": "overleaf",
        "description": "Read, edit, and compile the configured Overleaf instance through ChatOL.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list_projects", "list_files", "read_file", "save_file", "compile_project"]},
                "project_id": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    }


def _responses_create(base_url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{base_url}/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:800]
        raise WebError(exc.code, "openai_error", f"OpenAI Responses API returned HTTP {exc.code}: {body}") from exc


def _extract_function_calls(response: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for item in response.get("output") or []:
        if item.get("type") == "function_call":
            args = item.get("arguments") or "{}"
            if isinstance(args, str):
                with contextlib.suppress(json.JSONDecodeError):
                    args = json.loads(args or "{}")
            calls.append({"call_id": item.get("call_id") or item.get("id"), "name": item.get("name"), "arguments": args})
    return [call for call in calls if call.get("call_id") and call.get("name") == "overleaf"]


def _extract_output_text(response: dict[str, Any]) -> str:
    if response.get("output_text"):
        return str(response["output_text"])
    chunks = []
    for item in response.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("text"):
                    chunks.append(str(part["text"]))
    return "\n".join(chunks).strip()


def _conversation_text(messages: list[dict[str, Any]]) -> str:
    rows = []
    for msg in messages[-18:]:
        content = str(msg.get("content") or "")
        if len(content) > 2000:
            content = content[:2000] + "\n...[truncated]"
        rows.append(f"{msg.get('role', 'user')}: {content}")
    return "\n".join(rows) or "(none)"


def _current_context_text(context: dict[str, Any]) -> str:
    project = context.get("project") or {}
    file_info = context.get("file") or {}
    content = str(file_info.get("content") or "")
    if len(content) > 12000:
        content = content[:12000] + "\n...[truncated]"
    return (
        "Current editor context:\n"
        f"Project id: {project.get('id') or ''}\n"
        f"Project name: {project.get('name') or ''}\n"
        f"File path: {file_info.get('path') or ''}\n"
        f"File content:\n{content}"
    )


def make_handler(config: AppConfig, store: DataStore, *, login_ui: LoginUI | None = None) -> type[ChatOLWebHandler]:
    auth = HubAuth.create(config, login_ui=login_ui)

    class ConfiguredChatOLWebHandler(ChatOLWebHandler):
        pass

    ConfiguredChatOLWebHandler.config = config
    ConfiguredChatOLWebHandler.store = store
    ConfiguredChatOLWebHandler.auth = auth
    return ConfiguredChatOLWebHandler


def create_server(config: AppConfig, *, login_ui: LoginUI | None = None) -> ThreadingHTTPServer:
    store = DataStore(config)
    return ThreadingHTTPServer((config.host, config.port), make_handler(config, store, login_ui=login_ui))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ChatSite Overleaf editor web feature")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--init-only", action="store_true", help="Initialize the database and exit")
    args = parser.parse_args(argv)
    config = AppConfig.from_env(host=args.host, port=args.port, data_dir=args.data_dir)
    server = create_server(config)
    if args.init_only:
        return 0
    print(f"ChatSite Overleaf Web listening on http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
