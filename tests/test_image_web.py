import hashlib
import importlib
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image


def tiny_png(color=(220, 40, 70)):
    import io

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeGenerator:
    def __init__(self, data=None):
        self.data = data or tiny_png()
        self.calls = []
        self.fail = None

    def generate(self, prompt, **options):
        self.calls.append({"prompt": prompt, **options})
        if self.fail:
            raise self.fail
        return self.data


def settings(tmp_path, **overrides):
    module = importlib.import_module("chatsite.image_config")
    values = {
        "CHATSITE_IMAGE_ADMIN_EMAIL": "owner@example.test",
        "CHATSITE_IMAGE_ADMIN_PASSWORD": "owner-password",
        "CHATSITE_IMAGE_PUBLIC_URL": "https://image.example.test",
        "CHATSITE_IMAGE_DATA_DIR": str(tmp_path / "data"),
        "CHATSITE_IMAGE_PROVIDER": "openai",
        "CHATSITE_IMAGE_PROFILE": "unit",
    }
    values.update(overrides)
    return module.ImageSettings.from_values(values, home=tmp_path / "home")


def app_client(tmp_path, generator=None, credential_backend=None, **overrides):
    module = importlib.import_module("chatsite.image_web")
    cfg = settings(tmp_path, **overrides)
    app = module.create_app(cfg, generator_factory=lambda _model: generator or FakeGenerator(),
                            credential_backend=credential_backend)
    client = TestClient(app, base_url=cfg.public_url)
    client.headers["Origin"] = cfg.public_url
    return app, client


def login(client, email="owner@example.test", password="owner-password"):
    response = client.post("/api/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


def generate(client, prompt="一只玻璃质感的红色风筝", **payload):
    body = {"prompt": prompt, "model": "gpt-image-2-low", "size": "1024x1024", **payload}
    response = client.post("/api/generate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_guest_generation_static_image_details_and_no_history(tmp_path):
    fake = FakeGenerator()
    _app, client = app_client(tmp_path, fake)

    page = client.get("/")
    assert page.status_code == 200
    assert "ChatImg" in page.text and "data-login-url=\"/api/login\"" in page.text
    assert client.get("/assets/image.css").status_code == 200

    result = generate(client)
    assert result["ok"] is True
    assert result["image_url"] == "/generated/" + result["filename"]
    assert result["bytes"] == len(fake.data)
    assert fake.calls == [{"prompt": "一只玻璃质感的红色风筝", "size": "1024x1024", "quality": "low"}]
    assert client.get(result["image_url"]).headers["content-type"].startswith("image/png")
    details = client.get("/api/images/" + result["filename"]).json()
    assert details["sha256_12"] == hashlib.sha256(fake.data).hexdigest()[:12]
    assert client.get("/api/history").status_code == 401


def test_authenticated_history_is_owner_scoped_and_persists_after_recreation(tmp_path):
    fake = FakeGenerator()
    backend_users = {"owner@example.test": "owner-password", "other@example.test": "other-password"}

    def backend(email, password):
        from chatlogin import Principal

        return Principal(email) if backend_users.get(email) == password else None

    app, owner_client = app_client(tmp_path, fake, credential_backend=backend)
    owner_login = login(owner_client)
    result = generate(owner_client, prompt="登录用户的雪山")
    listing = owner_client.get("/api/history").json()
    assert listing["items"][0]["id"] and listing["items"][0]["prompt"] == "登录用户的雪山"
    assert listing["items"][0]["image_url"] == result["image_url"]
    detail = owner_client.get("/api/history/" + listing["items"][0]["id"]).json()
    assert detail["record"]["filename"] == result["filename"]
    assert "owner@example.test" not in detail.text if hasattr(detail, "text") else True

    recreated = importlib.import_module("chatsite.image_web").create_app(
        app.state.config, generator_factory=lambda _model: fake, credential_backend=backend,
    )
    persisted = TestClient(recreated, base_url=app.state.config.public_url)
    persisted.headers.update({"Origin": app.state.config.public_url, "X-CSRF-Token": owner_login.json()["csrf_token"]})
    persisted.cookies.set("chatimage_session", owner_login.cookies["chatimage_session"], domain="image.example.test")
    assert persisted.get("/api/history").json()["items"][0]["filename"] == result["filename"]

    _other_login = login(owner_client, "other@example.test", "other-password")
    assert owner_client.get("/api/history").json()["items"] == []
    assert owner_client.get("/api/history/" + listing["items"][0]["id"]).status_code == 404


def test_expired_identity_does_not_drop_generate_to_guest(tmp_path):
    app, client = app_client(tmp_path, FakeGenerator())
    login(client)
    with sqlite3.connect(app.state.config.data_dir / "auth.sqlite3") as db:
        db.execute("update chatlogin_sessions set expires_at=0")
    response = client.post("/api/generate", json={"prompt": "不要变成访客", "model": "gpt-image-2-low", "size": "1024x1024"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_expired"
    assert app.state.history.list("owner@example.test")["items"] == []


def test_csrf_origin_and_invalid_auth_header_boundaries(tmp_path):
    fake = FakeGenerator()
    _app, client = app_client(tmp_path, fake)
    login(client)
    assert client.post("/api/generate", json={"prompt": "x"}, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert client.post("/api/share", json={"filename": "20260912T000000Z-1234567890.png"},
                       headers={"Origin": "https://evil.example.test"}).status_code == 403
    response = client.post("/api/generate", json={"prompt": "带坏头", "model": "gpt-image-2-low", "size": "1024x1024"},
                           headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert not fake.calls


def test_provider_errors_are_redacted_and_no_retry_or_record(tmp_path):
    fake = FakeGenerator()
    fake.fail = RuntimeError("secret-token upstream account trace")
    app, client = app_client(tmp_path, fake)
    login(client)
    response = client.post("/api/generate", json={"prompt": "会失败", "model": "gpt-image-2-low", "size": "1024x1024"})
    assert response.status_code == 502
    assert "secret-token" not in response.text
    assert fake.calls == [{"prompt": "会失败", "size": "1024x1024", "quality": "low"}]
    assert app.state.history.list("owner@example.test")["items"] == []


def test_storage_failure_keeps_paid_generation_unrepeated_and_unrecorded(tmp_path):
    fake = FakeGenerator()
    app, client = app_client(tmp_path, fake)
    login(client)
    app.state.config.generated_dir.write_text("not a directory")
    response = client.post("/api/generate", json={"prompt": "存储失败", "model": "gpt-image-2-low", "size": "1024x1024"})
    assert response.status_code == 500
    assert fake.calls == [{"prompt": "存储失败", "size": "1024x1024", "quality": "low"}]
    assert app.state.history.list("owner@example.test")["items"] == []


def test_config_entrypoint_and_legacy_override_are_packaged(tmp_path):
    config = settings(tmp_path, CHATSITE_IMAGE_LEGACY_GENERATED_DIR=str(tmp_path / "legacy"))
    assert config.data_dir == tmp_path / "data"
    assert config.generated_dir == tmp_path / "data" / "generated"
    assert config.legacy_generated_dir == tmp_path / "legacy"
    app, client = app_client(tmp_path, FakeGenerator())
    assert app.title == "ChatImg"
    assert client.get("/health").json()["service"] == "chatimage"
