import importlib
import importlib.util
from pathlib import Path
import uuid

from fastapi.testclient import TestClient
import pytest

from chatsite.todo_config import TodoSettings


class FakeModel:
    def __init__(self, operations=None):
        self.operations = operations
        self.calls = []
        self.hook = None

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.hook:
            self.hook(kwargs)
        operations = self.operations
        if callable(operations):
            operations = operations(kwargs)
        return {'content': '这里是根据请求生成的任务建议。', 'operations': operations or [], 'response_id': 'response-test'}


def environment(tmp_path, model=None):
    assert importlib.util.find_spec('chatsite.todo_web') is not None
    module = importlib.import_module('chatsite.todo_web')
    cfg = TodoSettings.from_values({
        'CHATSITE_TODO_ADMIN_EMAIL': 'user@example.test',
        'CHATSITE_TODO_ADMIN_PASSWORD': 'test-password',
        'CHATSITE_TODO_API_BASE': 'https://api.example.test/v1',
        'CHATSITE_TODO_API_KEY': 'test-private-api-key',
        'CHATSITE_TODO_MODEL': 'test-model',
        'CHATSITE_TODO_PUBLIC_URL': 'https://todo.example.test',
        'CHATSITE_TODO_DATA_DIR': str(tmp_path / 'data'),
    })
    app = module.create_app(cfg, model_client=model or FakeModel())
    client = TestClient(app, base_url=cfg.public_url)
    client.headers['Origin'] = cfg.public_url
    return app, client


def login(client):
    response = client.post('/api/login', json={'email': 'user@example.test', 'password': 'test-password'})
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf_token']
    return response


def new_board(client):
    response = client.post('/api/boards', json={'title': '测试任务树'})
    assert response.status_code == 200, response.text
    return response.json()['board']


def mutation(client, board, ops, **extra):
    return client.patch('/api/boards/' + board['id'], json={
        'revision': board['revision'], 'request_id': str(uuid.uuid4()),
        'operations': ops, **extra,
    })


def test_login_auth_csrf_logout_and_secret_redaction(tmp_path):
    app, client = environment(tmp_path)
    assert client.get('/health').status_code == 200
    assert client.get('/api/boards').status_code == 401
    response = login(client)
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'secure' in cookie and 'samesite=lax' in cookie
    assert client.get('/api/session').json()['authenticated']
    settings = client.get('/api/settings')
    assert settings.status_code == 200 and settings.json()['configured']
    assert 'test-private-api-key' not in settings.text
    assert client.post('/api/boards', json={'title': 'x'}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert client.post('/api/boards', json={'title': 'x'}, headers={'Origin': 'https://evil.example.test'}).status_code == 403
    assert client.post('/api/logout').status_code == 200
    assert client.get('/api/boards').status_code == 401


def test_login_cross_origin_and_throttling(tmp_path):
    _, client = environment(tmp_path)
    assert client.post('/api/login', json={}, headers={'Origin': 'https://evil.example.test'}).status_code == 403
    for _ in range(8):
        assert client.post('/api/login', json={'email': 'user@example.test', 'password': 'wrong'}).status_code == 401
    assert client.post('/api/login', json={'email': 'user@example.test', 'password': 'wrong'}).status_code == 429


def test_mutate_undo_view_import_export_and_delete(tmp_path):
    _, client = environment(tmp_path)
    login(client)
    board = new_board(client)
    root = board['nodes'][0]['id']
    result = mutation(client, board, [{'op': 'create', 'node': {'id': 'child', 'parent_id': root, 'title': '子任务', 'body': '## PRD\n真实保存', 'status': 'pending', 'order': 0}}])
    assert result.status_code == 200, result.text
    changed = result.json()['board']
    assert len(changed['nodes']) == 2
    assert result.json()['change']['counts']['created'] == 1
    assert mutation(client, board, [{'op': 'update', 'id': root, 'fields': {'title': 'stale'}}]).status_code == 409
    view = {'pan': {'x': 20, 'y': 40}, 'zoom': 1.2, 'positions': {'child': {'x': 200, 'y': 120}}, 'collapsed': [root]}
    assert client.patch('/api/boards/' + board['id'] + '/view', json={'view': view}).status_code == 200
    latest = client.get('/api/boards/' + board['id']).json()['board']
    assert latest['revision'] == changed['revision'] and latest['view'] == view
    exported = client.get('/api/boards/' + board['id'] + '/export').json()
    imported = client.post('/api/import', json={'board': exported})
    assert imported.status_code == 200, imported.text
    assert imported.json()['board']['id'] != board['id']
    assert len(imported.json()['board']['nodes']) == 2
    undone = client.post('/api/boards/' + board['id'] + '/undo', json={'revision': changed['revision'], 'request_id': str(uuid.uuid4())})
    assert undone.status_code == 200, undone.text
    assert len(undone.json()['board']['nodes']) == 1
    assert client.get('/api/boards/' + board['id'] + '/history').status_code == 200
    assert client.request('DELETE', '/api/boards/' + board['id'], json={'revision': undone.json()['board']['revision'], 'confirm': False}).status_code == 400
    assert client.request('DELETE', '/api/boards/' + board['id'], json={'revision': undone.json()['board']['revision'], 'confirm': True}).status_code == 200
    assert client.get('/api/boards/' + board['id']).status_code == 404


@pytest.mark.parametrize('body', ['null', '[]', 'true', '{', '{"x":NaN}'])
def test_invalid_json_shapes_are_clean_errors(tmp_path, body):
    _, client = environment(tmp_path)
    login(client)
    result = client.post('/api/boards', content=body, headers={'Content-Type': 'application/json'})
    assert result.status_code == 400
    assert 'error' in result.json() and 'Traceback' not in result.text


def test_write_limit_and_static_traversal(tmp_path):
    _, client = environment(tmp_path)
    login(client)
    assert client.post('/api/boards', content=b'x' * 2_000_001).status_code == 413
    assert client.get('/assets/%2e%2e/todo_config.py').status_code == 404
    assert client.get('/assets/%2e%2e/%2e%2e/web.sqlite3').status_code == 404


def test_model_updates_tree_once_and_board_histories_are_isolated(tmp_path):
    fake = FakeModel(lambda args: [{'op': 'create', 'node': {'id': 'generated', 'parent_id': args['board']['nodes'][0]['id'], 'title': '模型创建的子任务'}}])
    _, client = environment(tmp_path, fake)
    login(client)
    board = new_board(client)
    request = {'message': '增加一个子任务', 'selected_node_id': None, 'revision': board['revision'], 'request_id': str(uuid.uuid4())}
    first = client.post('/api/boards/' + board['id'] + '/chat', json=request)
    assert first.status_code == 200, first.text
    assert len(first.json()['board']['nodes']) == 2
    assert first.json()['change']['counts']['created'] == 1
    assert client.post('/api/boards/' + board['id'] + '/chat', json=request).status_code == 200
    assert len(fake.calls) == 1
    assert len(client.get('/api/boards/' + board['id'] + '/messages').json()['messages']) == 2
    other = new_board(client)
    assert client.get('/api/boards/' + other['id'] + '/messages').json()['messages'] == []


def test_model_dangerous_changes_wait_for_confirmation(tmp_path):
    fake = FakeModel([{'op': 'delete', 'id': 'child'}])
    _, client = environment(tmp_path, fake)
    login(client)
    board = new_board(client)
    board = mutation(client, board, [{'op': 'create', 'node': {'id': 'child', 'parent_id': board['nodes'][0]['id'], 'title': '保留到确认'}}]).json()['board']
    response = client.post('/api/boards/' + board['id'] + '/chat', json={'message': '删除子任务', 'selected_node_id': None, 'revision': board['revision'], 'request_id': str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    proposal = response.json()['proposal']
    assert proposal and len(response.json()['board']['nodes']) == 2 and response.json()['change'] is None
    payload = {'proposal_id': proposal['id'], 'revision': board['revision'], 'request_id': str(uuid.uuid4()), 'confirm_destructive': True}
    applied = client.post('/api/boards/' + board['id'] + '/apply', json=payload)
    assert applied.status_code == 200, applied.text
    assert len(applied.json()['board']['nodes']) == 1
    assert client.post('/api/boards/' + board['id'] + '/apply', json=payload).status_code == 200
    messages = client.get('/api/boards/' + board['id'] + '/messages').json()['messages']
    assert messages[-1]['proposal'] is None and messages[-1]['change']


def test_model_cannot_overwrite_new_human_edit(tmp_path):
    fake = FakeModel(lambda args: [{'op': 'update', 'id': args['board']['nodes'][0]['id'], 'fields': {'title': '模型标题'}}])
    app, client = environment(tmp_path, fake)
    login(client)
    board = new_board(client)
    def concurrent_edit(args):
        app.state.boards.mutate(board['id'], 'user@example.test', board['revision'], 'human-race', [{'op': 'update', 'id': board['nodes'][0]['id'], 'fields': {'title': '用户最新标题'}}])
    fake.hook = concurrent_edit
    response = client.post('/api/boards/' + board['id'] + '/chat', json={'message': '改标题', 'selected_node_id': None, 'revision': board['revision'], 'request_id': str(uuid.uuid4())})
    assert response.status_code == 409
    assert client.get('/api/boards/' + board['id']).json()['board']['nodes'][0]['title'] == '用户最新标题'


def test_model_cannot_edit_outside_selected_branch(tmp_path):
    fake = FakeModel([{'op': 'update', 'id': 'outside', 'fields': {'title': '不允许'}}])
    _, client = environment(tmp_path, fake)
    login(client)
    board = new_board(client)
    root = board['nodes'][0]['id']
    board = mutation(client, board, [{'op': 'create', 'node': {'id': i, 'parent_id': root, 'title': i}} for i in ('inside', 'outside')]).json()['board']
    response = client.post('/api/boards/' + board['id'] + '/chat', json={'message': '修改', 'selected_node_id': 'inside', 'revision': board['revision'], 'request_id': str(uuid.uuid4())})
    assert response.status_code >= 400
    assert client.get('/api/boards/' + board['id']).json()['board']['revision'] == board['revision']
