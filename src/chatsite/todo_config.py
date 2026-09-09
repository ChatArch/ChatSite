"""Typed, server-side configuration for the ChatSite Todo feature."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from chatenv import BaseEnvConfig, EnvField, get_paths
from chatenv.store import EnvStore


class TodoWebConfig(BaseEnvConfig):
    """One canonical ChatEnv namespace for the Todo Web service."""

    _title = "ChatSite Todo"
    _aliases = ["chatsite-todo"]
    _storage_dir = "ChatSiteTodo"

    CHATSITE_TODO_HOST = EnvField("CHATSITE_TODO_HOST", "127.0.0.1", "监听地址")
    CHATSITE_TODO_PORT = EnvField("CHATSITE_TODO_PORT", "18086", "监听端口")
    CHATSITE_TODO_DATA_DIR = EnvField("CHATSITE_TODO_DATA_DIR", "", "运行数据目录")
    CHATSITE_TODO_PUBLIC_URL = EnvField("CHATSITE_TODO_PUBLIC_URL", "http://127.0.0.1:18086", "用户入口")
    CHATSITE_TODO_ALLOWED_ORIGINS = EnvField("CHATSITE_TODO_ALLOWED_ORIGINS", "", "额外同源入口，逗号分隔")
    CHATSITE_TODO_ADMIN_EMAIL = EnvField("CHATSITE_TODO_ADMIN_EMAIL", "", "共享登录邮箱")
    CHATSITE_TODO_ADMIN_PASSWORD = EnvField("CHATSITE_TODO_ADMIN_PASSWORD", "", "共享登录密码", is_sensitive=True)
    CHATSITE_TODO_API_BASE = EnvField("CHATSITE_TODO_API_BASE", "", "模型 API 入口")
    CHATSITE_TODO_API_KEY = EnvField("CHATSITE_TODO_API_KEY", "", "模型凭据", is_sensitive=True)
    CHATSITE_TODO_MODEL = EnvField("CHATSITE_TODO_MODEL", "", "模型名称")
    CHATSITE_TODO_PROTOCOL = EnvField("CHATSITE_TODO_PROTOCOL", "responses", "responses 或 chat_completions")
    CHATSITE_TODO_MODEL_TIMEOUT = EnvField("CHATSITE_TODO_MODEL_TIMEOUT", "90", "模型超时秒数")
    CHATSITE_TODO_SESSION_TTL = EnvField("CHATSITE_TODO_SESSION_TTL", "1209600", "会话有效秒数")
    CHATSITE_TODO_SECURE_COOKIE = EnvField("CHATSITE_TODO_SECURE_COOKIE", "", "留空时按入口 HTTPS 自动决定")

    @classmethod
    def test(cls) -> None:
        """Run one bounded no-edit request using the configured model protocol."""
        import click
        context = click.get_current_context(silent=True)
        paths = context.obj.get("paths") if context and isinstance(context.obj, dict) else None
        home = paths.home_dir if paths is not None else None
        probe_model(TodoSettings.from_profile(home=home))


def _url(value: str, *, origin_only: bool = False) -> str:
    try:
        part = urlsplit(value)
        _ = part.port
    except ValueError:
        raise ValueError("URL 格式不正确") from None
    if (part.scheme not in {"http", "https"} or not part.hostname or part.username
            or part.password or part.query or part.fragment or any(c.isspace() for c in value)):
        raise ValueError("URL 仅允许不带用户凭据、查询参数或片段的 HTTP(S) 入口")
    if origin_only and part.path not in {"", "/"}:
        raise ValueError("用户入口必须是独立站点的 origin")
    return value.rstrip("/")


@dataclass(frozen=True)
class TodoSettings:
    host: str
    port: int
    data_dir: Path
    public_url: str
    allowed_origins: frozenset[str]
    admin_email: str
    admin_password: str = field(repr=False)
    api_base: str
    api_key: str = field(repr=False)
    model: str
    protocol: str
    model_timeout: int
    session_ttl: int
    secure_cookie: bool

    @property
    def configured(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)

    @classmethod
    def from_values(cls, values: Mapping[str, object], *, home: str | Path | None = None) -> "TodoSettings":
        def text(name: str, default: str = "") -> str:
            value = values.get("CHATSITE_TODO_" + name, default)
            if value is None:
                return default
            if not isinstance(value, str):
                raise ValueError(f"CHATSITE_TODO_{name} 必须是字符串")
            return value

        def integer(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(text(name, str(default)))
            except ValueError:
                raise ValueError(f"CHATSITE_TODO_{name} 必须是整数") from None
            if not low <= value <= high:
                raise ValueError(f"CHATSITE_TODO_{name} 超出允许范围")
            return value

        email, password = text("ADMIN_EMAIL"), text("ADMIN_PASSWORD")
        if not email or "@" not in email or any(c.isspace() for c in email) or not password.strip():
            raise ValueError("必须配置有效的共享登录邮箱和密码")
        if len(email) > 254 or len(password) > 1024:
            raise ValueError("登录配置过长")
        home_dir = Path(get_paths(home).home_dir)
        raw_path = text("DATA_DIR") or str(home_dir / "chatsite" / "todo")
        raw_path = raw_path.replace("${CHATARCH_HOME}", str(home_dir)).replace("$CHATARCH_HOME", str(home_dir))
        if "$" in raw_path or "\x00" in raw_path:
            raise ValueError("数据目录含未知变量或无效字符")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = home_dir / path
        public_url = _url(text("PUBLIC_URL", "http://127.0.0.1:18086"), origin_only=True)
        origins = {public_url}
        for value in text("ALLOWED_ORIGINS").split(","):
            if value.strip():
                origins.add(_url(value.strip(), origin_only=True))
        api_base = text("API_BASE")
        if api_base:
            api_base = _url(api_base)
        protocol = text("PROTOCOL", "responses")
        if protocol not in {"responses", "chat_completions"}:
            raise ValueError("模型协议必须为 responses 或 chat_completions")
        secure = text("SECURE_COOKIE").lower()
        if secure not in {"", "true", "false", "1", "0"}:
            raise ValueError("SECURE_COOKIE 必须为 true 或 false")
        return cls(
            host=text("HOST", "127.0.0.1"), port=integer("PORT", 18086, 1, 65535),
            data_dir=path, public_url=public_url, allowed_origins=frozenset(origins),
            admin_email=email, admin_password=password, api_base=api_base, api_key=text("API_KEY"),
            model=text("MODEL"), protocol=protocol,
            model_timeout=integer("MODEL_TIMEOUT", 90, 5, 180),
            session_ttl=integer("SESSION_TTL", 1209600, 300, 2592000),
            secure_cookie=secure in {"true", "1"} if secure else public_url.startswith("https://"),
        )

    @classmethod
    def from_profile(cls, name: str | None = None, *, home: str | Path | None = None) -> "TodoSettings":
        store = EnvStore(get_paths(home).envs_dir)
        values = store.load_profile(TodoWebConfig, name) if name else store.load_active(TodoWebConfig)
        defaults = {key: value.default for key, value in TodoWebConfig.get_fields().items()}
        return cls.from_values({**defaults, **values}, home=home)


def probe_model(config: TodoSettings) -> None:
    """Make one protocol-specific no-edit request, never a fictitious success."""
    from chatsite.todo_model import ModelClient, ModelError
    if not config.configured:
        raise ValueError("模型配置不完整，请配置模型入口、名称和凭据")
    client = ModelClient(base_url=config.api_base, api_key=config.api_key,
                         model=config.model, protocol=config.protocol, timeout=config.model_timeout)
    probe = {"id": "connection-check", "title": "连接检查", "revision": 0, "nodes": [
        {"id": "connection-root", "parent_id": None, "title": "连接检查", "body": "",
         "status": "pending", "order": 0}
    ]}
    try:
        result = client.generate(message="只回复连接检查完成，不得修改任务树；operations 必须为空数组。",
                                 board=probe, history=[], selected_node_id=None, previous_response_id=None)
    except ModelError as exc:
        raise ValueError("模型验证失败：" + exc.message) from None
    if result["operations"]:
        raise ValueError("模型检查返回了意外的修改提案，未执行任何修改")
    print(f"ChatSite Todo 配置及 {config.protocol} 模型调用通过（无任务修改）。")


__all__ = ["TodoWebConfig", "TodoSettings", "probe_model"]
