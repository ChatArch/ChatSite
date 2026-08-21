from importlib.metadata import entry_points

from chatenv import EnvStore, get_paths

from chatsite.config import ChatsiteConfig


def test_chatenv_provider_entry_point_loads_typed_config():
    providers = {
        entry_point.name: entry_point
        for entry_point in entry_points(group="chatenv.configs")
    }

    assert providers["chatsite"].value == "chatsite.config"
    assert providers["chatsite"].load().ChatsiteConfig is ChatsiteConfig


def test_config_marks_api_key_sensitive():
    field = ChatsiteConfig.get_fields()["CHATSITE_API_KEY"]

    assert field.env_key == "CHATSITE_API_KEY"
    assert field.is_sensitive is True


def test_config_uses_chatenv_profile_storage_paths(tmp_path):
    store = EnvStore(get_paths(tmp_path).envs_dir)

    assert store.active_path(ChatsiteConfig) == tmp_path / "envs" / "Chatsite" / ".env"
    assert store.profile_path(ChatsiteConfig, "example") == (
        tmp_path / "envs" / "Chatsite" / "example.env"
    )
