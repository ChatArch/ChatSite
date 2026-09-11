"""Public ChatImg host with optional ChatLogin history."""
from __future__ import annotations

import argparse
import contextlib
from collections import OrderedDict, deque
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
from importlib import resources
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from requests.auth import HTTPDigestAuth
from starlette.concurrency import run_in_threadpool

from chatsite import __version__
from chatsite.image_auth import COOKIE, ImageAuth, login_asset
from chatsite.image_config import ImageSettings
from chatsite.image_history import ImageHistory
from chatsite.todo_state import StateError, WebState

MAX_PROMPT_CHARS = 1800
RATE_WINDOW_SECONDS = 300
RATE_LIMIT = 12
MAX_SHARE_BYTES = 20 * 1024 * 1024
SHARE_RATE_WINDOW_SECONDS = 300
SHARE_RATE_LIMIT = 10
SHARE_RATE_MAX_CLIENTS = 1024
SHARE_TIMEOUT = (5, 20)
FILENAME_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{10}\.png$")
MAX_BODY = 2_000_000
LOGGER = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=MAX_PROMPT_CHARS)
    model: str = Field("gpt-image-2-low", pattern=r"^gpt-image-2-(low|medium|high)$")
    size: str = Field("1024x1024", pattern=r"^(1024x1024|1536x1024|1024x1536)$")
    quality: str | None = Field(None, pattern=r"^(low|medium|high|auto)$")


class ShareRequest(BaseModel):
    filename: str = Field(..., pattern=r"^\d{8}T\d{6}Z-[0-9a-f]{10}\.png$")


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _same_origin(request: Request, config: ImageSettings) -> None:
    origins = request.headers.getlist("origin")
    origin = origins[0] if len(origins) == 1 else None
    if len(origins) > 1 or (origin and origin.rstrip("/") not in config.allowed_origins):
        raise StateError("bad_origin", "拒绝跨站写入请求", 403)
    if request.headers.get("sec-fetch-site", "").strip().lower() == "cross-site":
        raise StateError("bad_origin", "拒绝跨站写入请求", 403)


def _split_image_preset(model: str, quality: str | None) -> tuple[str, str]:
    suffix = model.rsplit("-", 1)[-1]
    return model, quality or suffix


def _validate_filename(filename: str) -> None:
    if not FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=404, detail="图片不存在。")


def _image_metadata(path: Path) -> dict[str, Any]:
    from PIL import Image

    data = path.read_bytes()
    with Image.open(path) as image:
        width, height = image.size
        fmt = image.format
        image.verify()
    if fmt != "PNG":
        raise RuntimeError("Generated file is not a PNG image")
    with Image.open(path) as image:
        image.load()
    digest = hashlib.sha256(data).hexdigest()
    return {"bytes": len(data), "width": width, "height": height, "sha256_12": digest[:12], "sha256": digest}


def _safe_image_bytes(path: Path, filename: str) -> tuple[bytes, dict[str, Any]]:
    _validate_filename(filename)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path / filename, flags)
    except (FileNotFoundError, NotADirectoryError, OSError):
        raise HTTPException(status_code=404, detail="图片不存在。") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SHARE_BYTES:
            raise HTTPException(status_code=404 if not stat.S_ISREG(info.st_mode) else 413, detail="图片不存在。")
        chunks: list[bytes] = []
        remaining = MAX_SHARE_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if len(data) > MAX_SHARE_BYTES:
        raise HTTPException(status_code=413, detail="图片超过 20 MiB，无法分享。")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if image.format != "PNG":
                raise ValueError("not png")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except Exception:
        raise HTTPException(status_code=400, detail="图片文件无效，无法分享。") from None
    digest = hashlib.sha256(data).hexdigest()
    return data, {"bytes": len(data), "width": width, "height": height, "sha256": digest, "sha256_12": digest[:12]}


def _redacted_error(_exc: Exception) -> str:
    return "图片生成失败，请稍后手动重试。"


def _make_generator_factory(config: ImageSettings):
    def factory(image_model: str):
        from chatimg.image import create_generator

        return create_generator(
            config.provider,
            profile=config.profile,
            api_mode=config.openai_api_mode or None,
            image_model=image_model,
            timeout_seconds=300,
        )

    return factory


def _share_config() -> tuple[str, str, str]:
    try:
        from chatshare.config import merged_chatshare_environ

        values = merged_chatshare_environ()
        base = values.get("CHATSHARE_DUFS_BASE_URL", "").strip()
        username = values.get("CHATSHARE_DUFS_USERNAME", "")
        password = values.get("CHATSHARE_DUFS_PASSWORD", "")
        parsed = urlsplit(base)
        _ = parsed.port
        valid = (
            parsed.scheme == "https" and bool(parsed.hostname)
            and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment
            and bool(username) and bool(password)
        )
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(status_code=503, detail="分享服务配置暂不可用。")
    return base.rstrip("/"), username, password


def _read_public_png(session: requests.Session, url: str) -> tuple[int, bytes | None]:
    response = None
    try:
        response = session.request("GET", url, stream=True, timeout=SHARE_TIMEOUT, allow_redirects=False)
        if response.status_code == 404:
            return 404, None
        if response.status_code != 200:
            return response.status_code, None
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "image/png":
            raise HTTPException(status_code=502, detail="分享服务返回的图片类型无效。")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_SHARE_BYTES:
                raise HTTPException(status_code=502, detail="分享服务返回的图片过大。")
            chunks.append(chunk)
        return 200, b"".join(chunks)
    finally:
        if response is not None:
            response.close()


def create_app(
    config: ImageSettings,
    *,
    generator_factory: Callable[[str], Any] | None = None,
    credential_backend: Callable[[str, str], Any] | None = None,
    login_ui=None,
) -> FastAPI:
    app = FastAPI(title="ChatImg", docs_url=None, redoc_url=None, openapi_url=None)
    config.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    history = ImageHistory(config.data_dir / "history.sqlite3")
    web_state = WebState(config.data_dir / "web.sqlite3", config.session_ttl)
    auth = ImageAuth.create(config, login_ui=login_ui, credential_backend=credential_backend)
    make_generator = generator_factory or _make_generator_factory(config)
    requests_by_ip: dict[str, deque[float]] = {}
    shares_by_ip: OrderedDict[str, deque[float]] = OrderedDict()
    share_rate_lock = threading.Lock()
    share_inflight = threading.BoundedSemaphore(2)
    publication_lock = threading.Lock()
    app.state.config, app.state.history, app.state.image_auth = config, history, auth

    @app.middleware("http")
    async def security(request: Request, next_handler):
        if request.headers.get("authorization"):
            response = JSONResponse(_error("bad_auth", "不支持的鉴权头"), status_code=401)
        elif request.method not in {"GET", "HEAD", "OPTIONS"}:
            try:
                _same_origin(request, config)
            except StateError as exc:
                response = JSONResponse(_error(exc.code, exc.message), status_code=exc.status)
            else:
                response = await next_handler(request)
        else:
            response = await next_handler(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; img-src 'self' data: https:; connect-src 'self'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        return response

    async def known_error(_request: Request, exc):
        return JSONResponse(_error(exc.code, exc.message), status_code=exc.status)

    app.add_exception_handler(StateError, known_error)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        message = exc.detail if isinstance(exc.detail, str) else "请求无法完成"
        return JSONResponse({"ok": False, "error": message}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(_request, exc):
        LOGGER.error("Image request failed: %s", type(exc).__name__)
        return JSONResponse(_error("internal_error", "请求未完成，请稍后手动重试"), status_code=500)

    def check_rate_limit(ip: str) -> None:
        now = time.time()
        bucket = requests_by_ip.setdefault(ip, deque())
        while bucket and now - bucket[0] > RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            raise StateError("rate_limited", "生图请求过多，请稍后再试", 429)
        bucket.append(now)

    def check_share_rate_limit(ip: str) -> None:
        now = time.time()
        with share_rate_lock:
            for known_ip, known_bucket in list(shares_by_ip.items()):
                while known_bucket and now - known_bucket[0] > SHARE_RATE_WINDOW_SECONDS:
                    known_bucket.popleft()
                if not known_bucket:
                    del shares_by_ip[known_ip]
            bucket = shares_by_ip.get(ip)
            if bucket is None:
                if len(shares_by_ip) >= SHARE_RATE_MAX_CLIENTS:
                    shares_by_ip.popitem(last=False)
                bucket = deque()
                shares_by_ip[ip] = bucket
            else:
                shares_by_ip.move_to_end(ip)
            if len(bucket) >= SHARE_RATE_LIMIT:
                raise StateError("share_rate_limited", "分享请求过多，请稍后重试。", 429)
            bucket.append(now)

    async def require_user(request: Request) -> str:
        return auth.require_read(request.cookies.get(COOKIE))

    @app.get("/health")
    def health():
        return {"ok": True, "service": "chatimage", "version": __version__}

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz() -> str:
        return "ok\n"

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        html = resources.files("chatsite").joinpath("image_static", "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    assets = Path(str(resources.files("chatsite").joinpath("image_static")))
    app.mount("/assets", StaticFiles(directory=assets, check_dir=False), name="image-assets")

    @app.get("/login")
    def login_page(request: Request, next: str | None = None):
        return auth.login_page(request, next)

    @app.get("/login/assets/{name}")
    def shared_login_asset(name: str):
        return login_asset(name)

    @app.get("/login/session")
    def login_session(request: Request):
        current = auth.session_payload(request.cookies.get(COOKIE))
        return current if current is not None else {"authenticated": False}

    @app.post("/api/login")
    async def login(request: Request):
        client_id = request.client.host if request.client else "unknown"
        if not web_state.login_allowed(client_id):
            raise StateError("rate_limited", "登录尝试过多，请五分钟后再试", 429)
        payload = await request.json()
        root = request.scope.get("root_path", "").rstrip("/")
        try:
            body, token = auth.login(payload, request.cookies.get(COOKIE), request.headers.get("x-csrf-token"),
                                     default_next=f"{root}/")
        except StateError as exc:
            if exc.code == "bad_login":
                web_state.login_failure(client_id)
            raise
        web_state.clear_login_failures(client_id)
        response = JSONResponse(body)
        response.set_cookie(COOKIE, token, httponly=True, secure=config.secure_cookie,
                            samesite="lax", max_age=config.session_ttl, path="/")
        return response

    @app.get("/api/session")
    async def session(request: Request, owner=Depends(require_user)):
        current = auth.session_payload(request.cookies.get(COOKIE))
        return {"authenticated": True, "email": owner, "csrf_token": current["csrf_token"]}

    @app.post("/api/logout")
    async def logout(request: Request):
        auth.logout(request.cookies.get(COOKIE), request.headers.get("x-csrf-token"))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/", secure=config.secure_cookie, httponly=True, samesite="lax")
        return response

    @app.get("/api/capabilities")
    def capabilities():
        return {
            "ok": True,
            "provider": config.provider,
            "models": ["gpt-image-2-low", "gpt-image-2-medium", "gpt-image-2-high"],
            "sizes": ["1024x1024", "1536x1024", "1024x1536"],
            "modes": {
                "text_to_image": True,
                "image_text_to_text": False,
                "image_text_to_image": False,
                "multi_image_text_to_image": False,
                "images_edits_endpoint": False,
                "images_variations_endpoint": False,
            },
        }

    @app.post("/api/generate")
    async def generate_image(payload: GenerateRequest, request: Request):
        prompt = payload.prompt.strip()
        if not prompt:
            raise StateError("bad_prompt", "Prompt is required")
        owner = auth.optional_write_owner(request.cookies.get(COOKIE), request.headers.get("x-csrf-token"))
        check_rate_limit(_client_ip(request))
        model, quality = _split_image_preset(payload.model, payload.quality)
        filename = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(5)}.png"
        started = time.monotonic()

        def work():
            generator = make_generator(model)
            return generator.generate(prompt, size=payload.size, quality=quality)

        try:
            image_bytes = await run_in_threadpool(work)
        except Exception as exc:
            raise StateError("generation_failed", _redacted_error(exc), 502) from None
        try:
            config.generated_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            output = config.generated_dir / filename
            output.write_bytes(image_bytes)
            meta = _image_metadata(output)
        except Exception as exc:
            with contextlib.suppress(Exception):
                (config.generated_dir / filename).unlink(missing_ok=True)
            raise StateError("storage_failed", "图片已生成但保存失败；请不要自动重试", 500) from exc
        root = request.scope.get("root_path", "").rstrip("/")
        image_url = f"{root}/generated/{filename}" if root else f"/generated/{filename}"
        result = {
            "ok": True,
            "image_url": image_url,
            "filename": filename,
            "bytes": meta["bytes"],
            "width": meta["width"],
            "height": meta["height"],
            "sha256_12": meta["sha256_12"],
            "model": model,
            "quality": quality,
            "size_requested": payload.size,
            "elapsed_sec": round(time.monotonic() - started, 2),
        }
        if owner is not None:
            history.add(owner=owner, prompt=prompt, model=model, size=payload.size, quality=quality,
                        filename=filename, image_url=result["image_url"], meta=meta)
        return result

    @app.get("/generated/{filename}")
    def generated(filename: str):
        _validate_filename(filename)
        for directory in [config.generated_dir, config.legacy_generated_dir]:
            if directory is None:
                continue
            path = directory / filename
            try:
                info = path.lstat()
            except OSError:
                continue
            if not stat.S_ISREG(info.st_mode) or path.is_symlink():
                break
            return FileResponse(path, media_type="image/png")
        raise HTTPException(status_code=404, detail="Not found")

    @app.get("/api/images/{filename}")
    def image_details(filename: str, request: Request):
        for directory in [config.generated_dir, config.legacy_generated_dir]:
            if directory is None:
                continue
            try:
                _data, meta = _safe_image_bytes(directory, filename)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            root = request.scope.get("root_path", "").rstrip("/")
            image_url = f"{root}/generated/{filename}" if root else f"/generated/{filename}"
            return {
                "ok": True,
                "image_url": image_url,
                "filename": filename,
                "bytes": meta["bytes"],
                "width": meta["width"],
                "height": meta["height"],
                "sha256_12": meta["sha256_12"],
            }
        raise HTTPException(status_code=404, detail="图片不存在。")

    @app.get("/api/history")
    def list_history(request: Request, limit: int = 40, offset: int = 0, owner=Depends(require_user)):
        return history.list(owner, limit=limit, offset=offset)

    @app.get("/api/history/{record_id}")
    def get_history(record_id: str, owner=Depends(require_user)):
        record = history.get(record_id, owner)
        if record is None:
            raise HTTPException(status_code=404, detail="Not found")
        return {"record": record}

    @app.get("/api/share/capabilities")
    def share_capabilities():
        try:
            _share_config()
            configured = True
        except HTTPException:
            configured = False
        return {"ok": True, "configured": configured}

    @app.post("/api/share")
    def share_image(payload: ShareRequest, request: Request):
        check_share_rate_limit(_client_ip(request))
        data, meta = _safe_image_bytes(config.generated_dir, payload.filename)
        base, username, password = _share_config()
        content_url = f"{base}/images/chatimg/{meta['sha256']}.png"
        if not share_inflight.acquire(blocking=False):
            raise StateError("share_busy", "当前分享请求较多，请稍后重试。", 429)
        session = requests.Session()
        session.trust_env = False
        try:
            with publication_lock:
                status, remote = _read_public_png(session, content_url)
                if status == 200:
                    if hashlib.sha256(remote or b"").hexdigest() != meta["sha256"]:
                        raise HTTPException(status_code=409, detail="分享地址已有不同内容，未覆盖。")
                    return {"ok": True, "url": content_url, "filename": payload.filename,
                            "sha256": meta["sha256"], "bytes": meta["bytes"], "reused": True}
                if status != 404:
                    raise HTTPException(status_code=502, detail="分享服务暂不可用，请稍后重试。")
                response = session.request(
                    "PUT", content_url, data=data,
                    headers={"Content-Type": "image/png", "If-None-Match": "*"},
                    auth=HTTPDigestAuth(username, password), timeout=SHARE_TIMEOUT, allow_redirects=False,
                )
                try:
                    put_status = response.status_code
                finally:
                    response.close()
                if put_status in (401, 403):
                    raise HTTPException(status_code=502, detail="分享服务鉴权失败，请稍后重试。")
                if not (200 <= put_status < 300 or put_status == 412):
                    raise HTTPException(status_code=502, detail="分享上传失败，请稍后手动重试。")
                return {"ok": True, "url": content_url, "filename": payload.filename,
                        "sha256": meta["sha256"], "bytes": meta["bytes"], "reused": put_status == 412}
        except requests.RequestException:
            raise HTTPException(status_code=502, detail="分享服务暂不可用，请稍后重试。") from None
        finally:
            session.close()
            share_inflight.release()

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="运行 ChatSite Image 文生图服务")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--profile")
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    config = ImageSettings.from_profile(args.profile, home=args.home)
    if args.host is not None:
        config = replace(config, host=args.host)
    if args.port is not None:
        if not 1 <= args.port <= 65535:
            parser.error("端口必须在 1..65535 范围")
        config = replace(config, port=args.port)
    import uvicorn

    uvicorn.run(create_app(config), host=config.host, port=config.port, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1", access_log=False, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
