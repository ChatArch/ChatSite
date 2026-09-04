from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_overleaf_web_is_a_chatsite_feature_entrypoint():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'chatsite-overleaf-web = "chatsite.overleaf_web:main"' in pyproject
    assert 'overleaf = ["ChatOL>=0.1.2,<0.2.0"]' in pyproject
    assert 'chatsite = ["overleaf_static/*"]' in pyproject


def test_overleaf_static_assets_are_checked_in_under_chatsite():
    static_dir = ROOT / "src" / "chatsite" / "overleaf_static"

    assert (static_dir / "index.html").read_text(encoding="utf-8").count("ChatSite") >= 2
    assert (static_dir / "app.js").read_text(encoding="utf-8")
    assert (static_dir / "style.css").read_text(encoding="utf-8")


def test_overleaf_web_settings_redact_secrets(monkeypatch, tmp_path):
    pytest.importorskip("chatol", reason="ChatOL optional extra is not installed")
    from chatsite.overleaf_web import AppConfig, DataStore

    monkeypatch.setenv("CHATSITE_WEB_ADMIN_PASSWORD", "admin-pass")
    monkeypatch.setenv("CHATSITE_OVERLEAF_DEFAULT_URL", "http://127.0.0.1:8090")
    monkeypatch.setenv("OVERLEAF_ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setenv("OVERLEAF_ADMIN_PASSWORD", "overleaf-pass")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    store = DataStore(AppConfig.from_env(data_dir=str(tmp_path)))
    settings = store.settings(include_secrets=False)

    assert settings["overleaf_base_url"] == "http://127.0.0.1:8090"
    assert settings["overleaf_email"] == "owner@example.test"
    assert settings["overleaf_password_configured"] is True
    assert settings["openai_api_key_configured"] is True
    assert "overleaf_password" not in settings
    assert "openai_api_key" not in settings

    first = store.create_conversation("first")
    second = store.create_conversation("second")
    store.set_conversation_response_id(first["id"], "resp_first")
    store.set_conversation_response_id(second["id"], "resp_second")
    assert store.conversation_response_id(first["id"]) == "resp_first"
    assert store.conversation_response_id(second["id"]) == "resp_second"


def test_overleaf_web_rejects_unsafe_remote_paths():
    pytest.importorskip("chatol", reason="ChatOL optional extra is not installed")
    from chatsite.overleaf_web import WebError, _normalize_remote_path, _safe_artifact_name

    assert _normalize_remote_path("/main.tex") == "main.tex"
    assert _safe_artifact_name("build/output.pdf") == "output.pdf"
    with pytest.raises(WebError):
        _normalize_remote_path("../secret.tex")
    with pytest.raises(WebError):
        _normalize_remote_path("folder//main.tex")
