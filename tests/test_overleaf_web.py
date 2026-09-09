from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_overleaf_web_is_a_chatsite_feature_entrypoint():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'chatsite-web = "chatsite.web:main"' in pyproject
    assert 'overleaf = ["ChatOL>=0.1.2,<0.2.0"]' in pyproject
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
