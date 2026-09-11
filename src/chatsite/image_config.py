"""Typed, server-side configuration for the ChatSite image feature."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from chatenv import BaseEnvConfig, EnvField, get_paths
from chatenv.store import EnvStore


class ImageWebConfig(BaseEnvConfig):
    """ChatEnv namespace for the packaged ChatSite image service."""

    _title = "ChatSite Image"
    _aliases = ["chatsite-image"]
    _storage_dir = "ChatSiteImage"

    CHATSITE_IMAGE_HOST = EnvField("CHATSITE_IMAGE_HOST", "127.0.0.1", "监听地址")
    CHATSITE_IMAGE_PORT = EnvField("CHATSITE_IMAGE_PORT", "18087", "监听端口")
    CHATSITE_IMAGE_DATA_DIR = EnvField("CHATSITE_IMAGE_DATA_DIR", "", "运行数据目录")
    CHATSITE_IMAGE_PUBLIC_URL = EnvField("CHATSITE_IMAGE_PUBLIC_URL", "http://127.0.0.1:18087", "用户入口")
    CHATSITE_IMAGE_ALLOWED_ORIGINS = EnvField("CHATSITE_IMAGE_ALLOWED_ORIGINS", "", "额外同源入口，逗号分隔")
    CHATSITE_IMAGE_ADMIN_EMAIL = EnvField("CHATSITE_IMAGE_ADMIN_EMAIL", "", "共享登录邮箱")
    CHATSITE_IMAGE_ADMIN_PASSWORD = EnvField("CHATSITE_IMAGE_ADMIN_PASSWORD", "", "共享登录密码", is_sensitive=True)
    CHATSITE_IMAGE_PROVIDER = EnvField("CHATSITE_IMAGE_PROVIDER", "openai", "ChatImg image provider")
    CHATSITE_IMAGE_PROFILE = EnvField("CHATSITE_IMAGE_PROFILE", "", "ChatImg/OpenAI ChatEnv profile")
    CHATSITE_IMAGE_OPENAI_API_MODE = EnvField("CHATSITE_IMAGE_OPENAI_API_MODE", "", "ChatImg OpenAI API mode")
    CHATSITE_IMAGE_SESSION_TTL = EnvField("CHATSITE_IMAGE_SESSION_TTL", "1209600", "会话有效秒数")
    CHATSITE_IMAGE_SECURE_COOKIE = EnvField("CHATSITE_IMAGE_SECURE_COOKIE", "", "留空时按入口 HTTPS 自动决定")
    CHATSITE_IMAGE_LEGACY_GENERATED_DIR = EnvField("CHATSITE_IMAGE_LEGACY_GENERATED_DIR", "", "旧匿名图片只读兼容目录")

    @classmethod
    def test(cls) -> None:
        import click

        context = click.get_current_context(silent=True)
        paths = context.obj.get("paths") if context and isinstance(context.obj, dict) else None
        home = paths.home_dir if paths is not None else None
        settings = ImageSettings.from_profile(home=home)
        if not settings.admin_email or not settings.profile:
            raise ValueError("请配置共享登录账号和 ChatImg profile")
        print("ChatSite Image 配置加载通过；未发起图片生成请求。")


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


def _path(value: str, home_dir: Path) -> Path:
    raw = value.replace("${CHATARCH_HOME}", str(home_dir)).replace("$CHATARCH_HOME", str(home_dir))
    if "$" in raw or "\x00" in raw:
        raise ValueError("数据目录含未知变量或无效字符")
    path = Path(raw).expanduser()
    return path if path.is_absolute() else home_dir / path


@dataclass(frozen=True)
class ImageSettings:
    host: str
    port: int
    data_dir: Path
    generated_dir: Path
    public_url: str
    allowed_origins: frozenset[str]
    admin_email: str
    admin_password: str = field(repr=False)
    provider: str
    profile: str
    openai_api_mode: str
    session_ttl: int
    secure_cookie: bool
    legacy_generated_dir: Path | None = None

    @classmethod
    def from_values(cls, values: Mapping[str, object], *, home: str | Path | None = None) -> "ImageSettings":
        def text(name: str, default: str = "") -> str:
            value = values.get("CHATSITE_IMAGE_" + name, default)
            if value is None:
                return default
            if not isinstance(value, str):
                raise ValueError(f"CHATSITE_IMAGE_{name} 必须是字符串")
            return value

        def integer(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(text(name, str(default)))
            except ValueError:
                raise ValueError(f"CHATSITE_IMAGE_{name} 必须是整数") from None
            if not low <= value <= high:
                raise ValueError(f"CHATSITE_IMAGE_{name} 超出允许范围")
            return value

        email, password = text("ADMIN_EMAIL"), text("ADMIN_PASSWORD")
        if not email or "@" not in email or any(c.isspace() for c in email) or not password.strip():
            raise ValueError("必须配置有效的共享登录邮箱和密码")
        if len(email) > 254 or len(password) > 1024:
            raise ValueError("登录配置过长")
        home_dir = Path(get_paths(home).home_dir)
        data_dir = _path(text("DATA_DIR") or str(home_dir / "chatsite" / "image"), home_dir)
        public_url = _url(text("PUBLIC_URL", "http://127.0.0.1:18087"), origin_only=True)
        origins = {public_url}
        for value in text("ALLOWED_ORIGINS").split(","):
            if value.strip():
                origins.add(_url(value.strip(), origin_only=True))
        provider = text("PROVIDER", "openai") or "openai"
        if provider not in {"openai"}:
            raise ValueError("当前 ChatSite Image 仅启用 ChatImg openai provider")
        secure = text("SECURE_COOKIE").lower()
        if secure not in {"", "true", "false", "1", "0"}:
            raise ValueError("SECURE_COOKIE 必须为 true 或 false")
        legacy = text("LEGACY_GENERATED_DIR")
        return cls(
            host=text("HOST", "127.0.0.1"),
            port=integer("PORT", 18087, 1, 65535),
            data_dir=data_dir,
            generated_dir=data_dir / "generated",
            public_url=public_url,
            allowed_origins=frozenset(origins),
            admin_email=email,
            admin_password=password,
            provider=provider,
            profile=text("PROFILE") or "default",
            openai_api_mode=text("OPENAI_API_MODE"),
            session_ttl=integer("SESSION_TTL", 1209600, 300, 2592000),
            secure_cookie=secure in {"true", "1"} if secure else public_url.startswith("https://"),
            legacy_generated_dir=_path(legacy, home_dir) if legacy else None,
        )

    @classmethod
    def from_profile(cls, name: str | None = None, *, home: str | Path | None = None) -> "ImageSettings":
        store = EnvStore(get_paths(home).envs_dir)
        values = store.load_profile(ImageWebConfig, name) if name else store.load_active(ImageWebConfig)
        defaults = {key: value.default for key, value in ImageWebConfig.get_fields().items()}
        return cls.from_values({**defaults, **values}, home=home)


__all__ = ["ImageWebConfig", "ImageSettings"]
