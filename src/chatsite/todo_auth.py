"""Thin ChatLogin host adapter for ChatSite Todo."""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from importlib import resources

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from chatlogin import (
    AccessDenied, CallbackBackend, Principal, SessionManager, SQLiteSessionStore,
    StoreFull, require_csrf, safe_next,
)
from chatlogin.ui import LoginUI

from chatsite.todo_config import TodoSettings
from chatsite.todo_state import StateError

COOKIE = "chattodo_session"
ASSETS = {"login.css": "text/css; charset=utf-8", "login.js": "application/javascript; charset=utf-8"}


def _credential_binding(config: TodoSettings) -> str:
    digest = hashlib.sha256()
    digest.update(config.admin_email.encode("utf-8"))
    digest.update(b"\0")
    digest.update(config.admin_password.encode("utf-8"))
    return digest.hexdigest()


def _constant_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(left.encode()).digest(), hashlib.sha256(right.encode()).digest())


@dataclass
class TodoAuth:
    config: TodoSettings
    sessions: SessionManager
    backend: CallbackBackend
    login_ui: LoginUI

    @classmethod
    def create(cls, config: TodoSettings, *, login_ui: LoginUI | None = None) -> "TodoAuth":
        binding = _credential_binding(config)

        def verify(email: str, password: str):
            if not _constant_equal(email, config.admin_email):
                return None
            if not _constant_equal(password, config.admin_password):
                return None
            return Principal(config.admin_email)

        store = SQLiteSessionStore(config.data_dir / "auth.sqlite3", max_sessions=1024)
        sessions = SessionManager(store, instance="chatsite-todo-" + binding[:16], ttl=config.session_ttl)
        ui = login_ui or LoginUI(title="ChatTodo", subtitle="使用 ChatSite 账号登录后继续。", palette="forest", guest_url=None)
        return cls(config=config, sessions=sessions, backend=CallbackBackend(verify), login_ui=ui)

    def _valid_session(self, token: str | None):
        session = self.sessions.resolve(token)
        if session is None:
            return None
        if session.principal.user_id != self.config.admin_email:
            self.sessions.revoke(token)
            return None
        return session

    def session_payload(self, token: str | None) -> dict | None:
        session = self._valid_session(token)
        if session is None:
            return None
        return {"authenticated": True, "email": session.principal.user_id, "csrf_token": session.csrf_token}

    def require_write(self, token: str | None, csrf: str | None) -> str:
        session = self._valid_session(token)
        if session is None:
            raise StateError("unauthenticated", "请先登录", 401)
        try:
            require_csrf(session, csrf)
        except AccessDenied:
            raise StateError("bad_csrf", "会话校验失败，请重新登录后重试", 403) from None
        return session.principal.user_id

    def require_read(self, token: str | None) -> str:
        session = self._valid_session(token)
        if session is None:
            raise StateError("unauthenticated", "请先登录", 401)
        return session.principal.user_id

    def login(self, payload: dict, previous_token: str | None = None, csrf: str | None = None,
              *, default_next: str = "/") -> tuple[dict, str]:
        extra = set(payload) - {"email", "username", "password", "next"}
        if extra or "password" not in payload or not ({"email", "username"} & set(payload)):
            raise StateError("bad_fields", "请求字段缺失或包含不支持的字段")
        email, username = payload.get("email"), payload.get("username")
        if email is not None and username is not None and email != username:
            raise StateError("bad_login_alias", "登录账号字段不一致")
        login_email = email if email is not None else username
        password = payload["password"]
        if not isinstance(login_email, str) or not isinstance(password, str):
            raise StateError("bad_login", "账号或密码错误", 401)
        if payload.get("next") is not None and not isinstance(payload["next"], str):
            raise StateError("bad_next", "登录跳转地址无效")
        prior = self._valid_session(previous_token)
        if prior is not None and csrf is not None:
            try:
                require_csrf(prior, csrf)
            except AccessDenied:
                raise StateError("bad_csrf", "会话校验失败，请重新登录后重试", 403) from None
        principal = self.backend.authenticate(login_email, password)
        if principal is None:
            raise StateError("bad_login", "账号或密码错误", 401)
        try:
            issued = self.sessions.issue(principal, previous_token=previous_token if prior is not None else None)
        except StoreFull:
            raise StateError("auth_store_full", "登录会话存储已满，请稍后重试", 503) from None
        return ({
            "authenticated": True,
            "email": principal.user_id,
            "csrf_token": issued.session.csrf_token,
            "next": safe_next(payload.get("next"), default=default_next),
        }, issued.token)

    def logout(self, token: str | None, csrf: str | None) -> None:
        self.require_write(token, csrf)
        self.sessions.revoke(token)

    def login_page(self, request: Request, next_url: str | None = None) -> HTMLResponse:
        root = request.scope.get("root_path", "").rstrip("/")
        context = {
            "login_url": f"{root}/api/login",
            "session_url": f"{root}/login/session",
            "logout_url": f"{root}/api/logout",
            "assets_path": f"{root}/login/assets",
            "next": safe_next(next_url, default=f"{root}/"),
        }
        return HTMLResponse(self.login_ui.render(context))


def login_asset(name: str) -> Response:
    media_type = ASSETS.get(name)
    if media_type is None:
        raise StateError("not_found", "页面或资源不存在", 404)
    data = (resources.files("chatlogin.web") / "assets" / name).read_bytes()
    return Response(data, media_type=media_type, headers={"Cache-Control": "public, max-age=3600"})
