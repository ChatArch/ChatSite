"""Private SQLite state for Todo web sessions and model conversations."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time


class StateError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _dump(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise StateError("invalid_data", "请求数据不能序列化") from None


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_id(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise StateError("bad_request_id", "request_id 格式无效")


class WebState:
    """Short-lived auth and replay-safe, per-owner/per-board model state."""

    def __init__(self, path: str | Path, session_ttl: int = 1209600):
        self.path = Path(path).absolute()
        self.session_ttl = session_ttl
        if type(session_ttl) is not int or session_ttl <= 0:
            raise ValueError("session_ttl must be positive")
        if any(p.is_symlink() for p in (self.path, *self.path.parents)):
            raise ValueError("Web state must not use a symlink path")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            if not self.path.is_file():
                raise ValueError("Web state path is not a regular file") from None
        else:
            os.close(descriptor)
        self.path.chmod(0o600)
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(
                    token_hash TEXT PRIMARY KEY, email TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures(client_hash TEXT NOT NULL, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS login_window ON login_failures(client_hash,at);
                CREATE TABLE IF NOT EXISTS conversations(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, board_id TEXT NOT NULL,
                    response_id TEXT, UNIQUE(owner,board_id));
                CREATE TABLE IF NOT EXISTS messages(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                    created_at REAL NOT NULL, change_json TEXT, proposal_json TEXT, request_id TEXT,
                    UNIQUE(conversation_id,request_id,role));
                CREATE TABLE IF NOT EXISTS chat_requests(
                    owner TEXT NOT NULL, board_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT,
                    status INTEGER NOT NULL DEFAULT 200, created_at REAL NOT NULL,
                    PRIMARY KEY(owner,board_id,request_id));
                CREATE TABLE IF NOT EXISTS proposals(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, board_id TEXT NOT NULL,
                    base_revision INTEGER NOT NULL, operations TEXT NOT NULL, summary TEXT NOT NULL,
                    selected_node_id TEXT, created_at REAL NOT NULL, applied INTEGER NOT NULL DEFAULT 0,
                    result TEXT);
                CREATE TABLE IF NOT EXISTS board_deletions(
                    owner TEXT NOT NULL, board_id TEXT NOT NULL, state TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(owner,board_id));
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

    def create_session(self, email: str) -> dict:
        token = secrets.token_urlsafe(48)
        with self.connection() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (_hash(token), email, time.time() + self.session_ttl))
        return {"token": token, "email": email, "csrf_token": _hash("csrf:" + token)}

    def session(self, token: str | None) -> dict | None:
        if not isinstance(token, str) or not token or len(token) > 256:
            return None
        with self.connection() as db:
            row = db.execute("SELECT email,expires FROM sessions WHERE token_hash=?", (_hash(token),)).fetchone()
            if not row:
                return None
            if row["expires"] <= time.time():
                db.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))
                return None
        return {"email": row["email"], "csrf_token": _hash("csrf:" + token)}

    def check_csrf(self, token: str | None, csrf: str | None) -> bool:
        session = self.session(token)
        return bool(session and isinstance(csrf, str) and hmac.compare_digest(
            session["csrf_token"].encode(), csrf.encode()
        ))

    def logout(self, token: str | None) -> None:
        if token:
            with self.connection() as db:
                db.execute("DELETE FROM sessions WHERE token_hash=?", (_hash(token),))

    def login_allowed(self, client: str) -> bool:
        with self.connection() as db:
            db.execute("DELETE FROM login_failures WHERE at < ?", (time.time() - 300,))
            count = db.execute("SELECT count(*) FROM login_failures WHERE client_hash=?", (_hash(client),)).fetchone()[0]
        return count < 8

    def login_failure(self, client: str) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO login_failures VALUES(?,?)", (_hash(client), time.time()))

    def clear_login_failures(self, client: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM login_failures WHERE client_hash=?", (_hash(client),))

    @staticmethod
    def _conversation(db, owner: str, board_id: str) -> dict:
        db.execute("INSERT OR IGNORE INTO conversations(id,owner,board_id) VALUES(?,?,?)",
                   (secrets.token_hex(16), owner, board_id))
        return dict(db.execute("SELECT * FROM conversations WHERE owner=? AND board_id=?", (owner, board_id)).fetchone())

    def conversation(self, owner: str, board_id: str) -> dict:
        with self.connection() as db:
            return self._conversation(db, owner, board_id)

    def messages(self, owner: str, board_id: str) -> list[dict]:
        with self.connection() as db:
            conversation = self._conversation(db, owner, board_id)
            rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY seq DESC LIMIT 200",
                              (conversation["id"],)).fetchall()
            result = []
            for row in reversed(rows):
                message = self._message(row)
                proposal = message.get("proposal")
                if proposal:
                    saved = db.execute("SELECT applied,result FROM proposals WHERE id=? AND owner=? AND board_id=?",
                                       (proposal["id"], owner, board_id)).fetchone()
                    if saved and saved["applied"]:
                        message["proposal"] = None
                        message["change"] = json.loads(saved["result"])["change"]
                result.append(message)
            return result

    @staticmethod
    def _message(row) -> dict:
        return {"id": row["id"], "role": row["role"], "content": row["content"], "created_at": row["created_at"],
                "change": json.loads(row["change_json"]) if row["change_json"] else None,
                "proposal": json.loads(row["proposal_json"]) if row["proposal_json"] else None}

    def add_message(self, owner: str, board_id: str, role: str, content: str, *, change=None, proposal=None, request_id=None) -> dict:
        if role not in {"user", "assistant"} or not isinstance(content, str) or len(content) > 65536:
            raise StateError("bad_message", "消息内容无效或过长")
        if request_id is not None:
            _request_id(request_id)
        with self.connection() as db:
            conversation = self._conversation(db, owner, board_id)
            message_id = secrets.token_hex(16)
            db.execute("INSERT OR IGNORE INTO messages(id,conversation_id,role,content,created_at,change_json,proposal_json,request_id) VALUES(?,?,?,?,?,?,?,?)",
                       (message_id, conversation["id"], role, content, time.time(), _dump(change) if change else None,
                        _dump(proposal) if proposal else None, request_id))
            if request_id is not None:
                row = db.execute("SELECT * FROM messages WHERE conversation_id=? AND request_id=? AND role=?",
                                 (conversation["id"], request_id, role)).fetchone()
            else:
                row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            return self._message(row)

    def begin_chat(self, owner: str, board_id: str, request_id: str, payload: dict) -> dict:
        _request_id(request_id)
        fingerprint = _hash(_dump(payload))
        now = time.time()
        with self.connection() as db:
            db.execute("DELETE FROM chat_requests WHERE state IN ('done','failed') AND created_at < ?", (now - 86400,))
            db.execute("UPDATE chat_requests SET state='failed',status=504,result=? WHERE state IN ('pending','generated') AND created_at < ?",
                       (_dump({"error": {"code": "model_timeout", "message": "上次模型请求已过期，请刷新任务树后重新发送"}}), now - 240))
            row = db.execute("SELECT * FROM chat_requests WHERE owner=? AND board_id=? AND request_id=?",
                             (owner, board_id, request_id)).fetchone()
            if row:
                if row["fingerprint"] != fingerprint:
                    raise StateError("request_mismatch", "同一 request_id 不能用于不同请求", 409)
                if row["state"] == "pending":
                    raise StateError("request_pending", "该模型请求仍在处理中，请勿重复发送", 409)
                return {"state": row["state"], "result": json.loads(row["result"]), "status": row["status"]}
            busy = db.execute("SELECT 1 FROM chat_requests WHERE owner=? AND board_id=? AND state IN ('pending','generated')", (owner, board_id)).fetchone()
            if busy:
                raise StateError("model_busy", "这棵任务树已有模型请求正在处理", 409)
            db.execute("INSERT INTO chat_requests(owner,board_id,request_id,fingerprint,state,created_at) VALUES(?,?,?,?,?,?)",
                       (owner, board_id, request_id, fingerprint, "pending", now))
            conversation = self._conversation(db, owner, board_id)
            return {"state": "new", "conversation": conversation}

    def save_generation(self, owner: str, board_id: str, request_id: str, result: dict) -> None:
        # Save the model result BEFORE graph writes, so recovery never calls the model twice.
        with self.connection() as db:
            row = db.execute("SELECT state,created_at FROM chat_requests WHERE owner=? AND board_id=? AND request_id=?",
                             (owner, board_id, request_id)).fetchone()
            if not row or row["state"] != "pending" or row["created_at"] < time.time() - 240:
                raise StateError("request_expired", "模型请求已失效，任务树未更新", 409)
            db.execute("UPDATE chat_requests SET state='generated',result=? WHERE owner=? AND board_id=? AND request_id=?",
                       (_dump(result), owner, board_id, request_id))

    def finish_chat(self, owner: str, board_id: str, request_id: str, result: dict, *, status: int = 200, response_id=None) -> None:
        with self.connection() as db:
            db.execute("UPDATE chat_requests SET state=?,result=?,status=? WHERE owner=? AND board_id=? AND request_id=?",
                       ("done" if status < 400 else "failed", _dump(result), status, owner, board_id, request_id))
            if response_id is not None:
                db.execute("UPDATE conversations SET response_id=? WHERE owner=? AND board_id=?", (response_id, owner, board_id))

    def create_proposal(self, owner: str, board_id: str, request_id: str, revision: int, operations: list, summary: str, selected_node_id=None) -> dict:
        proposal_id = _hash(_dump([owner, board_id, request_id]))[:32]
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO proposals(id,owner,board_id,base_revision,operations,summary,selected_node_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (proposal_id, owner, board_id, revision, _dump(operations), summary[:10000], selected_node_id, time.time()))
        return self.proposal(owner, board_id, proposal_id)

    def proposal(self, owner: str, board_id: str, proposal_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=? AND owner=? AND board_id=?", (proposal_id, owner, board_id)).fetchone()
            if not row:
                raise StateError("not_found", "提案不存在", 404)
            if not row["applied"] and row["created_at"] < time.time() - 86400:
                raise StateError("proposal_expired", "提案已过期，请重新讨论生成", 409)
            return {"id": row["id"], "summary": row["summary"], "operations": json.loads(row["operations"]),
                    "base_revision": row["base_revision"], "selected_node_id": row["selected_node_id"],
                    "applied": bool(row["applied"]), "result": json.loads(row["result"]) if row["result"] else None}

    def finish_proposal(self, owner: str, board_id: str, proposal_id: str, result: dict) -> None:
        with self.connection() as db:
            db.execute("UPDATE proposals SET applied=1,result=? WHERE id=? AND owner=? AND board_id=?",
                       (_dump(result), proposal_id, owner, board_id))

    def prepare_board_deletion(self, owner: str, board_id: str) -> dict:
        now = time.time()
        with self.connection() as db:
            db.execute("DELETE FROM board_deletions WHERE state='complete' AND updated_at < ?", (now - 86400,))
            existing = db.execute("SELECT 1 FROM board_deletions WHERE owner=? AND board_id=?",
                                  (owner, board_id)).fetchone() is not None
            db.execute("INSERT OR IGNORE INTO board_deletions VALUES(?,?,?,?,?)",
                       (owner, board_id, "prepared", now, now))
            result = dict(db.execute("SELECT * FROM board_deletions WHERE owner=? AND board_id=?",
                                     (owner, board_id)).fetchone())
            result["existing"] = existing
            return result

    @staticmethod
    def _delete_board_state(db, owner: str, board_id: str) -> None:
        row = db.execute("SELECT id FROM conversations WHERE owner=? AND board_id=?", (owner, board_id)).fetchone()
        if row:
            db.execute("DELETE FROM messages WHERE conversation_id=?", (row["id"],))
        db.execute("DELETE FROM conversations WHERE owner=? AND board_id=?", (owner, board_id))
        db.execute("DELETE FROM chat_requests WHERE owner=? AND board_id=?", (owner, board_id))
        db.execute("DELETE FROM proposals WHERE owner=? AND board_id=?", (owner, board_id))

    def complete_board_deletion(self, owner: str, board_id: str) -> None:
        with self.connection() as db:
            self._delete_board_state(db, owner, board_id)
            db.execute("UPDATE board_deletions SET state='complete',updated_at=? WHERE owner=? AND board_id=?",
                       (time.time(), owner, board_id))

    def delete_board_state(self, owner: str, board_id: str) -> None:
        with self.connection() as db:
            self._delete_board_state(db, owner, board_id)
