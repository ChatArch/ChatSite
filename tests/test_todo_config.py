import importlib
import importlib.util

import pytest


def module():
    assert importlib.util.find_spec('chatsite.todo_config') is not None
    return importlib.import_module('chatsite.todo_config')


def values(tmp_path):
    return {
        'CHATSITE_TODO_ADMIN_EMAIL': 'user@example.test',
        'CHATSITE_TODO_ADMIN_PASSWORD': 'local-test-password',
        'CHATSITE_TODO_API_BASE': 'https://api.example.test/v1',
        'CHATSITE_TODO_API_KEY': 'local-test-key',
        'CHATSITE_TODO_MODEL': 'test-model',
        'CHATSITE_TODO_PROTOCOL': 'responses',
        'CHATSITE_TODO_PUBLIC_URL': 'https://todo.example.test',
        'CHATSITE_TODO_DATA_DIR': str(tmp_path / 'state'),
    }


def test_config_uses_explicit_values_and_hides_secrets(tmp_path):
    m = module()
    config = m.TodoSettings.from_values(values(tmp_path), home=tmp_path / 'home')
    assert config.admin_email == 'user@example.test'
    assert config.protocol == 'responses'
    assert config.host == '127.0.0.1'
    assert config.port == 18086
    assert config.configured
    assert config.secure_cookie
    assert 'local-test-key' not in repr(config)
    assert 'local-test-password' not in repr(config)
    assert not config.data_dir.exists()


@pytest.mark.parametrize('key,value', [
    ('CHATSITE_TODO_ADMIN_EMAIL', ''),
    ('CHATSITE_TODO_ADMIN_PASSWORD', ''),
    ('CHATSITE_TODO_PROTOCOL', 'automatic'),
    ('CHATSITE_TODO_PORT', '0'),
    ('CHATSITE_TODO_PORT', 'bad'),
    ('CHATSITE_TODO_PUBLIC_URL', 'javascript:alert(1)'),
    ('CHATSITE_TODO_PUBLIC_URL', 'https://user:secret@example.test'),
    ('CHATSITE_TODO_API_BASE', 'file:///etc/passwd'),
    ('CHATSITE_TODO_API_BASE', 'https://example.test/v1?key=bad'),
    ('CHATSITE_TODO_DATA_DIR', '$UNKNOWN/state'),
])
def test_config_rejects_unsafe_values(tmp_path, key, value):
    data = values(tmp_path)
    data[key] = value
    with pytest.raises(ValueError):
        module().TodoSettings.from_values(data, home=tmp_path / 'home')


def test_effective_home_expansion_and_no_ambient_key(tmp_path, monkeypatch):
    m = module()
    data = values(tmp_path)
    data['CHATSITE_TODO_DATA_DIR'] = '$CHATARCH_HOME/todo'
    data['CHATSITE_TODO_API_KEY'] = ''
    monkeypatch.setenv('OPENAI_API_KEY', 'ambient-must-not-be-used')
    config = m.TodoSettings.from_values(data, home=tmp_path / 'selected-home')
    assert config.data_dir == tmp_path / 'selected-home/todo'
    assert config.api_key == ''
    assert not config.configured


def test_named_profile_does_not_activate_or_consume_other_profile(tmp_path):
    m = module()
    from chatenv import get_paths
    from chatenv.store import EnvStore
    home = tmp_path / 'home'
    store = EnvStore(get_paths(home).envs_dir)
    store.save_profile(m.TodoWebConfig, 'testing', values(tmp_path))
    config = m.TodoSettings.from_profile('testing', home=home)
    assert config.model == 'test-model'
    assert config.api_key == 'local-test-key'


def test_configuration_test_uses_real_protocol_instead_of_models_listing(tmp_path, monkeypatch):
    m = module()
    import httpx
    from chatsite.todo_model import ModelClient
    data = values(tmp_path)
    from chatenv import get_paths
    from chatenv.store import EnvStore
    home = tmp_path / 'protocol-home'
    monkeypatch.setenv('CHATARCH_HOME', str(home))
    EnvStore(get_paths(home).envs_dir).save_active(m.TodoWebConfig, data)
    calls = []
    def generate(self, **kwargs):
        calls.append(kwargs)
        return {'content': '连接检查完成', 'operations': [], 'response_id': None}
    def unsupported_listing(**kwargs):
        raise AssertionError('models listing is not the configured protocol')
    monkeypatch.setattr(ModelClient, 'generate', generate)
    monkeypatch.setattr(httpx, 'Client', unsupported_listing)
    m.TodoWebConfig.test()
    assert len(calls) == 1 and len(calls[0]['board']['nodes']) == 1


def test_chatenv_test_loads_active_profile_and_honors_home(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from chatenv.cli import cli
    from chatenv import get_paths
    from chatenv.store import EnvStore
    from chatsite.todo_model import ModelClient
    m = module()
    home = tmp_path / 'selected-home'
    EnvStore(get_paths(home).envs_dir).save_active(m.TodoWebConfig, values(tmp_path))
    calls = []
    def generate(self, **kwargs):
        calls.append(kwargs)
        return {'content': '连接正常', 'operations': [], 'response_id': None}
    monkeypatch.setattr(ModelClient, 'generate', generate)
    result = CliRunner().invoke(cli, ['--home', str(home), 'test', '-t', 'chatsite-todo', '-I'])
    assert result.exit_code == 0, str(result.exception)
    assert len(calls) == 1
    assert 'local-test-key' not in result.output and 'local-test-password' not in result.output


def test_schema_marks_sensitive_fields():
    m = module()
    fields = m.TodoWebConfig.get_fields()
    assert fields['CHATSITE_TODO_API_KEY'].is_sensitive
    assert fields['CHATSITE_TODO_ADMIN_PASSWORD'].is_sensitive
