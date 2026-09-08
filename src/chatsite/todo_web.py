"""Authenticated ChatSite Todo web feature; domain operations live in ChatTodo."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import hmac
from importlib import resources
import json
import logging
import os
from pathlib import Path
import re
import threading

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from chattodo.board import BoardError, BoardStore, apply_operations
from chatsite import __version__
from chatsite.todo_config import TodoSettings
from chatsite.todo_model import ModelClient, ModelError, enforce_scope, requires_confirmation
from chatsite.todo_state import StateError, WebState

COOKIE = "chattodo_session"
MAX_BODY = 2_000_000
LOGGER = logging.getLogger(__name__)


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _revision(value) -> int:
    if type(value) is not int or value < 0:
        raise StateError("bad_revision", "revision 必须是非负整数")
    return value


def _request_id(value) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise StateError("bad_request_id", "request_id 格式无效")
    return value


def _boolean(payload, name, default=False) -> bool:
    value = payload.get(name, default)
    if type(value) is not bool:
        raise StateError("bad_confirmation", "确认字段必须是布尔值")
    return value


def _fields(payload, allowed, required=()):
    if set(payload) - set(allowed) or not set(required).issubset(payload):
        raise StateError("bad_fields", "请求字段缺失或包含不支持的字段")


async def _body(request: Request) -> dict:
    limit = 4096 if request.url.path == "/api/login" else MAX_BODY
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > limit:
            raise StateError("body_too_large", "请求内容过大", 413)
        data.extend(chunk)

    def reject_constant(_):
        raise ValueError("non-finite JSON")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        payload = json.loads(data.decode("utf-8") or "{}", object_pairs_hook=unique, parse_constant=reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        raise StateError("bad_json", "请求不是有效的 JSON 对象") from None
    if not isinstance(payload, dict):
        raise StateError("bad_json", "请求必须是 JSON 对象")
    pending = [payload]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str) and re.search(r"[\ud800-\udfff]", value):
            raise StateError("bad_json", "内容包含无效 Unicode 字符")
    return payload


def create_app(config: TodoSettings, *, model_client=None, board_store=None) -> FastAPI:
    app = FastAPI(title="ChatTodo", docs_url=None, redoc_url=None, openapi_url=None)
    boards = board_store or BoardStore(config.data_dir / "boards.sqlite3")
    web = WebState(config.data_dir / "web.sqlite3", config.session_ttl)
    model = model_client if model_client is not None else ModelClient(
        base_url=config.api_base, api_key=config.api_key, model=config.model,
        protocol=config.protocol, timeout=config.model_timeout,
    )
    model_slots = threading.BoundedSemaphore(2)
    app.state.boards, app.state.web_state, app.state.config = boards, web, config

    @app.middleware("http")
    async def security(request: Request, next_handler):
        origin = request.headers.get("origin")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            (origin and origin.rstrip("/") not in config.allowed_origins)
            or request.headers.get("sec-fetch-site") == "cross-site"
        ):
            response = JSONResponse(_error("bad_origin", "拒绝跨站写入请求"), status_code=403)
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

    for kind in (BoardError, StateError, ModelError):
        app.add_exception_handler(kind, known_error)

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc):
        return JSONResponse(_error("not_found" if exc.status_code == 404 else "http_error", "页面或资源不存在" if exc.status_code == 404 else "请求无法完成"), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(_request, exc):
        LOGGER.error("Todo request failed: %s", type(exc).__name__)
        return JSONResponse(_error("internal_error", "请求未完成，请刷新核对当前状态后再操作"), status_code=500)

    async def require_user(request: Request) -> str:
        token = request.cookies.get(COOKIE)
        session = web.session(token)
        if not session:
            raise StateError("unauthenticated", "请先登录", 401)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not web.check_csrf(token, request.headers.get("x-csrf-token")):
            raise StateError("bad_csrf", "会话校验失败，请重新登录后重试", 403)
        return session["email"]

    @app.get("/health")
    def health():
        build = os.getenv("CHATSITE_TODO_BUILD", "dev")
        if not re.fullmatch(r"[0-9a-f]{7,40}", build):
            build = "dev"
        return {"ok": True, "service": "chattodo", "version": __version__, "build": build, "model_configured": config.configured}

    @app.get("/")
    def index():
        try:
            html = resources.files("chatsite").joinpath("todo_static", "index.html").read_text(encoding="utf-8")
        except FileNotFoundError:
            raise StateError("assets_missing", "页面资源尚未安装", 503) from None
        return HTMLResponse(html)

    assets = Path(str(resources.files("chatsite").joinpath("todo_static")))
    app.mount("/assets", StaticFiles(directory=assets, check_dir=False), name="todo-assets")

    @app.post("/api/login")
    async def login(request: Request):
        client_id = request.client.host if request.client else "unknown"
        if not web.login_allowed(client_id):
            raise StateError("rate_limited", "登录尝试过多，请五分钟后再试", 429)
        body = await _body(request)
        _fields(body, {"email", "password"}, {"email", "password"})
        email, password = body["email"], body["password"]
        valid = isinstance(email, str) and isinstance(password, str) and len(email) <= 254 and len(password) <= 1024
        if valid:
            valid = hmac.compare_digest(hashlib.sha256(email.encode()).digest(), hashlib.sha256(config.admin_email.encode()).digest())
            valid = hmac.compare_digest(hashlib.sha256(password.encode()).digest(), hashlib.sha256(config.admin_password.encode()).digest()) and valid
        if not valid:
            web.login_failure(client_id)
            raise StateError("bad_login", "账号或密码错误", 401)
        web.clear_login_failures(client_id)
        session = web.create_session(config.admin_email)
        response = JSONResponse({"authenticated": True, "email": session["email"], "csrf_token": session["csrf_token"]})
        response.set_cookie(COOKIE, session["token"], httponly=True, secure=config.secure_cookie,
                            samesite="lax", max_age=config.session_ttl, path="/")
        return response

    @app.get("/api/session")
    async def session(request: Request, owner=Depends(require_user)):
        current = web.session(request.cookies.get(COOKIE))
        return {"authenticated": True, "email": owner, "csrf_token": current["csrf_token"]}

    @app.post("/api/logout")
    async def logout(request: Request, _owner=Depends(require_user)):
        web.logout(request.cookies.get(COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/", secure=config.secure_cookie, httponly=True, samesite="lax")
        return response

    @app.get("/api/settings")
    async def settings(_owner=Depends(require_user)):
        return {"model": config.model, "protocol": config.protocol, "configured": config.configured}

    @app.get("/api/boards")
    async def list_boards(owner=Depends(require_user)):
        return {"boards": boards.list(owner)}

    @app.post("/api/boards")
    async def create_board(request: Request, owner=Depends(require_user)):
        body = await _body(request)
        _fields(body, {"title"})
        return {"board": boards.create(owner, title=body.get("title", "我的任务树"))}

    @app.get("/api/boards/{board_id}")
    async def get_board(board_id: str, owner=Depends(require_user)):
        return {"board": boards.get(board_id, owner)}

    @app.patch("/api/boards/{board_id}")
    async def mutate_board(board_id: str, request: Request, owner=Depends(require_user)):
        body = await _body(request)
        _fields(body, {"revision", "request_id", "operations", "confirm_destructive"}, {"revision", "request_id", "operations"})
        return boards.mutate(board_id, owner, _revision(body["revision"]), _request_id(body["request_id"]),
                             body["operations"], confirm_destructive=_boolean(body, "confirm_destructive"))

    @app.patch("/api/boards/{board_id}/view")
    async def save_view(board_id: str, request: Request, owner=Depends(require_user)):
        body = await _body(request)
        _fields(body, {"view"}, {"view"})
        return boards.save_view(board_id, owner, body["view"])

    @app.post("/api/boards/{board_id}/undo")
    async def undo(board_id: str, request: Request, owner=Depends(require_user)):
        body = await _body(request)
        _fields(body, {"revision", "request_id"}, {"revision", "request_id"})
        return boards.undo(board_id, owner, _revision(body["revision"]), _request_id(body["request_id"]))

    @app.get("/api/boards/{board_id}/history")
    async def history(board_id: str, owner=Depends(require_user)):
        return {"changes": boards.history(board_id, owner)}

    @app.get("/api/boards/{board_id}/export")
    async def export(board_id: str, owner=Depends(require_user)):
        return JSONResponse(boards.get(board_id, owner), headers={"Content-Disposition": 'attachment; filename="chattodo-board.json"'})

    @app.post("/api/import")
    async def import_board(request: Request, owner=Depends(require_user)):
        payload = await _body(request)
        _fields(payload, {"board"}, {"board"})
        data = payload["board"]
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
            raise StateError("bad_import", "导入文件必须包含 nodes 数组")
        result = boards.create(owner, title=data.get("title", "导入的任务树"), nodes=data["nodes"])
        try:
            if "view" in data:
                boards.save_view(result["id"], owner, data["view"])
        except BoardError:
            boards.delete(result["id"], owner, result["revision"], confirm=True)
            raise
        return {"board": boards.get(result["id"], owner)}

    @app.delete("/api/boards/{board_id}")
    async def delete_board(board_id: str, request: Request, owner=Depends(require_user)):
        body = await _body(request)
        _fields(body, {"revision", "confirm"}, {"revision", "confirm"})
        boards.delete(board_id, owner, _revision(body["revision"]), confirm=_boolean(body, "confirm"))
        web.delete_board_state(owner, board_id)
        return {"ok": True}

    @app.get("/api/boards/{board_id}/messages")
    async def messages(board_id: str, owner=Depends(require_user)):
        boards.get(board_id, owner)
        conversation = web.conversation(owner, board_id)
        return {"conversation_id": conversation["id"], "messages": web.messages(owner, board_id)}

    def generate_model(message, board, prior, selected):
        if not model_slots.acquire(blocking=False):
            raise StateError("model_busy", "模型服务正忙，请稍后重试", 429)
        try:
            # Each request is stateless at the provider. Never continue an unacknowledged
            # function-call response; local conversation histories are board-isolated.
            return model.generate(message=message, board=board, history=prior,
                                  selected_node_id=selected, previous_response_id=None)
        finally:
            model_slots.release()

    @app.post("/api/boards/{board_id}/chat")
    async def chat(board_id: str, request: Request, owner=Depends(require_user)):
        body = await _body(request)
        _fields(body, {"message", "selected_node_id", "revision", "request_id"}, {"message", "revision", "request_id"})
        message, selected = body["message"], body.get("selected_node_id")
        if not isinstance(message, str) or not message.strip() or len(message) > 16000:
            raise StateError("bad_message", "消息不能为空且不能超过 16000 字符")
        if selected is not None and (not isinstance(selected, str) or not selected):
            raise StateError("bad_selection", "选中的节点无效")
        revision, request_id = _revision(body["revision"]), _request_id(body["request_id"])
        board = boards.get(board_id, owner)
        payload = {"message": message, "selected_node_id": selected, "revision": revision}
        reserved = web.begin_chat(owner, board_id, request_id, payload)
        if reserved["state"] in {"done", "failed"}:
            result = reserved["result"]
            if reserved["state"] == "done":
                result["board"] = boards.get(board_id, owner)
            return JSONResponse(result, status_code=reserved["status"])
        try:
            if reserved["state"] == "new":
                if board["revision"] != revision:
                    raise StateError("revision_conflict", "任务树已被修改，请刷新后重新发送", 409)
                if selected is not None and selected not in {n["id"] for n in board["nodes"]}:
                    raise StateError("bad_selection", "选中的节点已不存在", 409)
                if not config.configured:
                    raise StateError("model_not_configured", "模型尚未配置，请联系管理员", 503)
                prior = web.messages(owner, board_id)
                web.add_message(owner, board_id, "user", message, request_id=request_id)
                generation = await run_in_threadpool(generate_model, message, board, prior, selected)
                enforce_scope(generation["operations"], board, selected)
                apply_operations(board["nodes"], generation["operations"], confirm_destructive=True)
                generation["high_risk"] = requires_confirmation(generation["operations"], board["nodes"])
                generation["base_revision"] = revision
                generation["selected_node_id"] = selected
                web.save_generation(owner, board_id, request_id, generation)
            else:
                generation = reserved["result"]
            operations = generation["operations"]
            proposal, change = None, None
            if generation["high_risk"]:
                if boards.get(board_id, owner)["revision"] != generation["base_revision"]:
                    raise StateError("revision_conflict", "任务树已改变，提案未应用；请重新讨论", 409)
                saved = web.create_proposal(owner, board_id, request_id, generation["base_revision"], operations,
                                            generation["content"], generation["selected_node_id"])
                proposal = {key: saved[key] for key in ("id", "summary", "operations", "base_revision")}
                content = "以下变更尚未应用，需要你确认。\n\n" + generation["content"]
            elif operations:
                mutation = boards.mutate(board_id, owner, generation["base_revision"], "chat_" + request_id,
                                          operations, actor="model", confirm_destructive=False)
                change = mutation["change"]
                content = "已更新任务树。\n\n" + generation["content"]
            else:
                content = generation["content"]
            reply = web.add_message(owner, board_id, "assistant", content, change=change, proposal=proposal, request_id=request_id)
            result = {"message": reply, "board": boards.get(board_id, owner), "change": change, "proposal": proposal}
            web.finish_chat(owner, board_id, request_id, result, response_id=generation.get("response_id"))
            return result
        except (BoardError, StateError, ModelError) as exc:
            web.finish_chat(owner, board_id, request_id, _error(exc.code, exc.message), status=exc.status)
            raise

    @app.post("/api/boards/{board_id}/apply")
    async def apply_proposal(board_id: str, request: Request, owner=Depends(require_user)):
        body = await _body(request)
        _fields(body, {"proposal_id", "revision", "request_id", "confirm_destructive"}, {"proposal_id", "revision", "request_id", "confirm_destructive"})
        _request_id(body["request_id"])
        revision = _revision(body["revision"])
        if not _boolean(body, "confirm_destructive"):
            raise StateError("confirmation_required", "请确认提案影响后再应用")
        if not isinstance(body["proposal_id"], str):
            raise StateError("bad_proposal", "提案标识无效")
        board = boards.get(board_id, owner)
        proposal = web.proposal(owner, board_id, body["proposal_id"])
        if proposal["applied"]:
            return {"board": board, "change": proposal["result"]["change"]}
        if revision != proposal["base_revision"]:
            raise StateError("revision_conflict", "提案已过时，请重新讨论生成", 409)
        enforce_scope(proposal["operations"], board, proposal["selected_node_id"])
        result = boards.mutate(board_id, owner, revision, "proposal_" + proposal["id"], proposal["operations"],
                               actor="model_confirmed", confirm_destructive=True)
        web.finish_proposal(owner, board_id, proposal["id"], result)
        return result

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="运行 ChatSite Todo 任务树工作台")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--profile")
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    config = TodoSettings.from_profile(args.profile, home=args.home)
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
