from pathlib import Path
import hashlib
import json
import re
import sqlite3
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_overleaf_web_is_a_chatsite_feature_entrypoint():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'chatsite-web = "chatsite.web:main"' in pyproject
    assert 'overleaf = ["ChatOL>=0.1.2,<0.2.0", "ChatLogin[ui]>=0.1.3,<0.2.0"]' in pyproject
    assert 'todo = ["ChatTodo>=0.1.0,<0.2.0", "ChatLogin[web]>=0.1.2,<0.2.0"' in pyproject
    assert '[tool.setuptools.package-data]' in pyproject
    assert '"web_static/*"' in pyproject


def test_overleaf_static_assets_are_checked_in_under_chatsite():
    static_dir = ROOT / "src" / "chatsite" / "web_static"

    assert (static_dir / "index.html").read_text(encoding="utf-8").count("ChatSite") >= 2
    assert "Overleaf 编辑器" in (static_dir / "overleaf.html").read_text(encoding="utf-8")
    assert (static_dir / "hub.js").read_text(encoding="utf-8")
    assert (static_dir / "app.js").read_text(encoding="utf-8")
    assert (static_dir / "style.css").read_text(encoding="utf-8")


def test_public_source_does_not_embed_local_deployment_policy():
    scanned = []
    for path in [
        ROOT / "docs" / "overleaf-editor-web.md",
        ROOT / "scripts" / "run-web.sh",
        ROOT / "src" / "chatsite" / "web.py",
        ROOT / "src" / "chatsite" / "web_static" / "index.html",
        ROOT / "src" / "chatsite" / "web_static" / "overleaf.html",
    ]:
        scanned.append(path.read_text(encoding="utf-8"))
    combined = "\n".join(scanned)

    assert not re.search(r"/(?:home|Users)/[A-Za-z0-9_.-]+", combined)
    assert "SITES.md" not in combined
    assert not re.search(r"[A-Za-z0-9._%+-]+@(?!example\.(?:test|invalid|com)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}", combined)


def test_hub_shared_login_uses_ui_only_extra_and_package_root_assets():
    source = (ROOT / "src" / "chatsite" / "web.py").read_text(encoding="utf-8")

    assert 'resources.files("chatlogin").joinpath("web", "assets", name)' in source
    assert 'resources.files("chatlogin.web")' not in source
    assert "Sign in with the configured ChatSite account." not in source


def test_overleaf_web_settings_redact_secrets(monkeypatch, tmp_path):
    pytest.importorskip("chatol", reason="ChatOL optional extra is not installed")
    from chatsite.web import AppConfig, DataStore

    monkeypatch.setenv("CHATSITE_WEB_ADMIN_PASSWORD", "admin-pass")
    monkeypatch.delenv("CHATSITE_WEB_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_MODEL", raising=False)
    monkeypatch.setenv("CHATSITE_OVERLEAF_DEFAULT_URL", "http://127.0.0.1:8090")
    monkeypatch.setenv("OVERLEAF_ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setenv("OVERLEAF_ADMIN_PASSWORD", "overleaf-pass")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    store = DataStore(AppConfig.from_env(data_dir=str(tmp_path)))
    settings = store.settings(include_secrets=False)

    assert settings["overleaf_base_url"] == "http://127.0.0.1:8090"
    assert settings["overleaf_email"] == "owner@example.test"
    assert settings["overleaf_password_configured"] is True
    assert settings["openai_model"] == "gpt-5.5"
    assert settings["openai_api_key_configured"] is True
    assert "overleaf_password" not in settings
    assert "openai_api_key" not in settings

    first = store.create_conversation("first")
    second = store.create_conversation("second")
    store.set_conversation_response_id(first["id"], "resp_first")
    store.set_conversation_response_id(second["id"], "resp_second")
    assert store.conversation_response_id(first["id"]) == "resp_first"
    assert store.conversation_response_id(second["id"]) == "resp_second"


def test_openai_apple_env_names_are_supported(monkeypatch, tmp_path):
    pytest.importorskip("chatol", reason="ChatOL optional extra is not installed")
    from chatsite.web import AppConfig

    monkeypatch.setenv("CHATSITE_WEB_ADMIN_PASSWORD", "admin-pass")
    monkeypatch.delenv("CHATSITE_WEB_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-5.5")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.test/openai/v1")
    config = AppConfig.from_env(data_dir=str(tmp_path))

    assert config.default_openai_model == "gpt-5.5"
    assert config.openai_base_url == "https://example.test/openai/v1"


def test_overleaf_web_rejects_unsafe_remote_paths():
    pytest.importorskip("chatol", reason="ChatOL optional extra is not installed")
    from chatsite.web import WebError, _normalize_remote_path, _safe_artifact_name

    assert _normalize_remote_path("/main.tex") == "main.tex"
    assert _safe_artifact_name("build/output.pdf") == "output.pdf"
    with pytest.raises(WebError):
        _normalize_remote_path("../secret.tex")
    with pytest.raises(WebError):
        _normalize_remote_path("folder//main.tex")


def hub_config(monkeypatch, tmp_path, password="admin-pass"):
    pytest.importorskip("chatol", reason="ChatOL optional extra is not installed")
    from chatsite.web import AppConfig

    monkeypatch.setenv("CHATSITE_WEB_ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setenv("CHATSITE_WEB_ADMIN_PASSWORD", password)
    monkeypatch.setenv("CHATSITE_WEB_PUBLIC_URL", "https://hub.example.test")
    monkeypatch.setenv("CHATSITE_WEB_ALLOWED_ORIGINS", "http://127.0.0.1:18082")
    return AppConfig.from_env(data_dir=str(tmp_path))


def request(handler, method, path, *, body=None, cookie=None, csrf=None, origin="https://hub.example.test"):
    payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
    from io import BytesIO
    instance = handler.__new__(handler)
    response = {}
    chunks = []
    instance.command = method
    instance.path = path
    instance.request_version = "HTTP/1.1"
    instance.rfile = BytesIO(payload or b"")
    from email.message import Message
    headers = Message()
    if payload is not None:
        headers["Content-Length"] = str(len(payload))
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if origin:
        headers["Origin"] = origin
    instance.headers = headers
    instance.send_response = lambda status, message=None: response.update(status=status)
    instance.send_header = lambda name, value: response.setdefault("headers", []).append((name, value))
    instance.end_headers = lambda: None
    instance.wfile = type("Writer", (), {"write": lambda _self, data: chunks.append(data)})()
    instance._dispatch(method)
    raw = b"".join(chunks).decode("utf-8", errors="replace")
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = raw
    return response["status"], dict(response.get("headers", [])), data, raw


def test_hub_uses_chatlogin_shared_login_bootstrap_and_separate_store(monkeypatch, tmp_path):
    from chatsite import web

    config = hub_config(monkeypatch, tmp_path)
    store = web.DataStore(config)
    handler = web.make_handler(config, store)

    status, headers, data, raw = request(handler, "GET", "/login/session")
    assert status == 200 and data == {"authenticated": False}
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"

    status, _headers, _data, raw = request(handler, "GET", "/login?next=/overleaf")
    assert status == 200
    assert "data-session-url=\"/login/session\"" in raw
    assert "data-login-url=\"/api/login\"" in raw
    assert "使用已配置的 ChatSite 账号登录后继续。" in raw

    status, _headers, _data, raw = request(handler, "GET", "/login/assets/login.js")
    assert status == 200 and "fetch(" in raw

    status, headers, data, _raw = request(handler, "POST", "/api/login", body={
        "username": "admin@example.test", "password": "admin-pass", "next": "https://evil.example.test/path",
    })
    assert status == 200
    assert data["email"] == "admin@example.test"
    assert data["next"] == "/"
    assert isinstance(data["csrf_token"], str)
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    cookie = headers["Set-Cookie"]
    assert all(value in cookie for value in ("chatsite_session=", "HttpOnly", "Secure", "SameSite=Lax", "Path=/"))

    token = re.search(r"chatsite_session=([^;]+)", cookie).group(1)
    auth_db = tmp_path / "auth.sqlite3"
    assert auth_db.exists()
    with sqlite3.connect(auth_db) as db:
        row = db.execute("select principal, csrf from chatlogin_sessions").fetchone()
    assert "admin-pass" not in row[0]
    assert row[1] == data["csrf_token"]
    with sqlite3.connect(tmp_path / "chatsite.sqlite3") as db:
        assert db.execute("select count(*) from settings").fetchone()[0] > 0

    status, headers, session, _raw = request(handler, "GET", "/api/me", cookie=f"chatsite_session={token}")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert session == {"authenticated": True, "email": "admin@example.test", "csrf_token": data["csrf_token"]}


def test_hub_rejects_legacy_rows_bad_csrf_cross_origin_and_rotated_credentials(monkeypatch, tmp_path):
    from chatsite import web

    config = hub_config(monkeypatch, tmp_path)
    store = web.DataStore(config)
    legacy = "legacy-token-value"
    legacy_digest = hashlib.sha256(legacy.encode("utf-8")).hexdigest()
    now = time.time()
    with sqlite3.connect(tmp_path / "chatsite.sqlite3") as db:
        db.execute("insert into sessions(token_hash, user_email, created_at, expires_at) values(?,?,?,?)",
                   (legacy_digest, "admin@example.test", now, now + 3600))
        assert db.execute("select user_email from sessions where token_hash=? and expires_at>?",
                          (legacy_digest, now)).fetchone() == ("admin@example.test",)
    handler = web.make_handler(config, store)
    assert request(handler, "GET", "/api/session", cookie=f"chatsite_session={legacy}")[0] == 401

    status, headers, data, _raw = request(handler, "POST", "/api/login", body={"email": "admin@example.test", "password": "admin-pass"})
    assert status == 200
    token = re.search(r"chatsite_session=([^;]+)", headers["Set-Cookie"]).group(1)
    cookie = f"chatsite_session={token}"
    assert request(handler, "PUT", "/api/settings", cookie=cookie, csrf="wrong", body={"openai_model": "test"})[0] == 403
    assert request(handler, "PUT", "/api/settings", cookie=cookie, csrf=data["csrf_token"],
                   origin="https://evil.example.test", body={"openai_model": "test"})[0] == 403
    assert request(handler, "PUT", "/api/settings", cookie=cookie, csrf=data["csrf_token"], body={"openai_model": "test"})[0] == 200

    rotated_config = hub_config(monkeypatch, tmp_path, password="rotated-pass")
    rotated_handler = web.make_handler(rotated_config, web.DataStore(rotated_config))
    assert request(rotated_handler, "GET", "/api/session", cookie=cookie)[0] == 401

    logout_status, logout_headers, _logout_data, _logout_raw = request(
        handler, "POST", "/api/logout", cookie=cookie, csrf=data["csrf_token"]
    )
    assert logout_status == 200
    assert logout_headers["Cache-Control"] == "no-store"
    assert logout_headers["X-Content-Type-Options"] == "nosniff"
    assert "Path=/" in logout_headers["Set-Cookie"]
    assert request(handler, "GET", "/api/session", cookie=cookie)[0] == 401
