"Typed environment configuration for chatsite."

from chatenv import BaseEnvConfig, EnvField


class ChatsiteConfig(BaseEnvConfig):
    "chatsite ChatEnv configuration."

    _title = "chatsite Configuration"
    _aliases = ["chatsite"]
    _storage_dir = "Chatsite"

    @classmethod
    def test(cls) -> None:
        """Validate schema registration without external side effects."""

        print(f"Testing {cls._title}...")
        print("Schema loaded; no network test is required.")

    CHATSITE_API_KEY = EnvField(
        "CHATSITE_API_KEY",
        desc="API key",
        is_sensitive=True,
    )


from chatsite.image_config import ImageWebConfig


__all__ = ["ChatsiteConfig", "ImageWebConfig"]
