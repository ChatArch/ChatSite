import hashlib
import importlib
import importlib.util
from html.parser import HTMLParser
import socket
import sqlite3
import threading
import time
from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from chatlogin.ui import LoginUI

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


def login_with_username(client, next='/'):
    response = client.post('/api/login', json={'username': 'user@example.test', 'password': 'test-password', 'next': next})
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


def test_chatlogin_sessions_persist_in_separate_digest_store_and_legacy_sessions_are_rejected(tmp_path):
    app, client = environment(tmp_path)
    response = login(client)
    token = response.cookies['chattodo_session']
    csrf = response.json()['csrf_token']
    web_db = app.state.web_state.path
    auth_db = tmp_path / 'data' / 'auth.sqlite3'
    assert auth_db.exists()
    assert auth_db != web_db
    with sqlite3.connect(auth_db) as db:
        rows = db.execute('select digest, principal, csrf from chatlogin_sessions').fetchall()
    assert len(rows) == 1
    assert token not in str(rows)
    assert 'test-password' not in str(rows) and 'display_name": ""' in str(rows)
    assert response.json()['email'] == 'user@example.test'

    module = importlib.import_module('chatsite.todo_web')
    cfg = app.state.config
    recreated = TestClient(module.create_app(cfg, model_client=FakeModel()), base_url=cfg.public_url)
    recreated.headers.update({'Origin': cfg.public_url, 'X-CSRF-Token': csrf})
    recreated.cookies.set('chattodo_session', token, domain='todo.example.test')
    assert recreated.get('/api/session').json()['email'] == 'user@example.test'
    assert recreated.post('/api/logout').status_code == 200
    assert recreated.get('/api/session').status_code == 401

    legacy = 'legacy-' + uuid.uuid4().hex
    legacy_digest = hashlib.sha256(legacy.encode('utf-8')).hexdigest()
    with sqlite3.connect(web_db) as db:
        db.execute('create table if not exists sessions(token_hash text primary key, email text not null, expires real not null)')
        db.execute('insert into sessions values(?,?,strftime("%s","now")+3600)', (legacy_digest, 'user@example.test'))
        # Prove this fixture matches the valid lookup used by the old store.
        assert db.execute('select email from sessions where token_hash=? and expires>?',
                          (legacy_digest, time.time())).fetchone() == ('user@example.test',)
    legacy_client = TestClient(module.create_app(cfg, model_client=FakeModel()), base_url=cfg.public_url)
    legacy_client.headers['Origin'] = cfg.public_url
    legacy_client.cookies.set('chattodo_session', legacy, domain='todo.example.test')
    assert legacy_client.get('/api/session').status_code == 401


def test_chatlogin_session_expiry_is_rejected(tmp_path):
    app, client = environment(tmp_path)
    login(client)
    with sqlite3.connect(tmp_path / 'data' / 'auth.sqlite3') as db:
        db.execute('update chatlogin_sessions set expires_at=0')
    assert client.get('/api/session').status_code == 401
    with sqlite3.connect(tmp_path / 'data' / 'auth.sqlite3') as db:
        assert db.execute('select count(*) from chatlogin_sessions').fetchone()[0] == 0


def test_login_alias_next_shared_ui_assets_and_custom_login_ui(tmp_path):
    app, client = environment(tmp_path)
    entry = client.get('/', follow_redirects=False)
    assert entry.status_code == 303
    assert entry.headers['location'] == '/login?next=/'
    page = client.get('/login?next=/boards/demo')
    assert page.status_code == 200
    assert 'ChatTodo' in page.text and 'data-login-url="/api/login"' in page.text
    assert client.get('/login/assets/login.css').status_code == 200
    assert client.get('/login/assets/login.js').status_code == 200
    assert client.get('/login/assets/nope.css').status_code == 404
    assert client.get('/assets/login.css').status_code in {404, 405}

    response = login_with_username(client, next='https://evil.example.test/path')
    assert response.json()['next'] == '/'
    assert response.json()['authenticated'] is True and response.json()['email'] == 'user@example.test'
    conflict = client.post('/api/login', json={'email': 'user@example.test', 'username': 'other@example.test', 'password': 'test-password'})
    assert conflict.status_code == 400
    assert client.post('/api/login', json={'email': 'user@example.test', 'password': 'test-password', 'next': 42}).status_code == 400

    module = importlib.import_module('chatsite.todo_web')
    cfg = app.state.config
    custom = module.create_app(cfg, model_client=FakeModel(), login_ui=LoginUI(renderer=lambda context: '<main>custom ' + context['login_url'] + '</main>'))
    custom_client = TestClient(custom, base_url=cfg.public_url)
    custom_client.headers['Origin'] = cfg.public_url
    assert 'custom /api/login' in custom_client.get('/login').text


def test_mounted_root_redirect_and_login_context_preserve_prefix(tmp_path):
    app, _client = environment(tmp_path)
    mounted = TestClient(app, base_url='https://todo.example.test/labs/todo', root_path='/labs/todo')
    mounted.headers['Origin'] = app.state.config.public_url
    entry = mounted.get('/', follow_redirects=False)
    assert entry.status_code == 303
    assert entry.headers['location'] == '/labs/todo/login?next=/labs/todo/'
    page = mounted.get('/login?next=/labs/todo/')
    assert 'data-login-url="/labs/todo/api/login"' in page.text
    assert 'data-next="/labs/todo/"' in page.text


class SharedLoginMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.root = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'chatlogin' in attrs.get('class', '').split():
            self.root = attrs


@pytest.fixture(params=['', '/mounted'], ids=['root', 'mounted'])
def login_contract_environment(tmp_path, request):
    app, _client = environment(tmp_path)
    prefix = request.param
    host = FastAPI()
    host.mount(prefix or '/', app)
    with TestClient(host, base_url=app.state.config.public_url, raise_server_exceptions=False) as client:
        client.headers['Origin'] = app.state.config.public_url
        yield app, client, prefix


@pytest.mark.parametrize('cookie', [None, 'invalid-session'])
def test_login_bootstrap_anonymous_preserves_protected_session(login_contract_environment, cookie):
    _app, client, prefix = login_contract_environment
    if cookie:
        client.cookies.set('chattodo_session', cookie)
    assert client.get(prefix + '/api/session').status_code == 401
    response = client.get(prefix + '/login/session')
    assert response.status_code == 200, response.text
    assert response.json() == {'authenticated': False}
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers


def test_login_bootstrap_authenticated_csrf_and_logout(login_contract_environment):
    _app, client, prefix = login_contract_environment
    logged_in = client.post(prefix + '/api/login', json={
        'email': 'user@example.test', 'password': 'test-password',
    })
    assert logged_in.status_code == 200
    response = client.get(prefix + '/login/session')
    assert response.status_code == 200, response.text
    assert response.json() == {
        'authenticated': True, 'email': 'user@example.test',
        'csrf_token': logged_in.json()['csrf_token'],
    }
    assert response.json() == client.get(prefix + '/api/session').json()
    assert response.headers['cache-control'] == 'no-store'
    assert 'set-cookie' not in response.headers
    for secret in ('test-password', 'test-private-api-key', logged_in.cookies['chattodo_session']):
        assert secret not in response.text
    logout = client.post(prefix + '/api/logout', headers={'X-CSRF-Token': response.json()['csrf_token']})
    assert logout.status_code == 200
    anonymous = client.get(prefix + '/login/session')
    assert anonymous.status_code == 200
    assert anonymous.json() == {'authenticated': False}
    assert client.get(prefix + '/api/session').status_code == 401


def test_login_bootstrap_expired_session_is_anonymous(login_contract_environment):
    app, client, prefix = login_contract_environment
    response = client.post(prefix + '/api/login', json={
        'username': 'user@example.test', 'password': 'test-password',
    })
    assert response.status_code == 200
    with sqlite3.connect(app.state.config.data_dir / 'auth.sqlite3') as db:
        db.execute('update chatlogin_sessions set expires_at=0')
    anonymous = client.get(prefix + '/login/session')
    assert anonymous.status_code == 200, anonymous.text
    assert anonymous.json() == {'authenticated': False}
    assert client.get(prefix + '/api/session').status_code == 401


def test_login_bootstrap_storage_failure_is_not_anonymous(login_contract_environment):
    app, client, prefix = login_contract_environment
    response = client.post(prefix + '/api/login', json={
        'username': 'user@example.test', 'password': 'test-password',
    })
    assert response.status_code == 200
    # Break only this test's synthetic store; a real storage error must remain 500.
    with sqlite3.connect(app.state.config.data_dir / 'auth.sqlite3') as db:
        db.execute('drop table chatlogin_sessions')
    failed = client.get(prefix + '/login/session')
    assert failed.status_code == 500, failed.text
    assert failed.json()['error']['code'] == 'internal_error'
    assert 'authenticated' not in failed.json()
    assert 'sqlite' not in failed.text and 'chatlogin_sessions' not in failed.text
    assert client.get(prefix + '/api/session').status_code == 500


def test_login_page_points_to_public_bootstrap(login_contract_environment):
    _app, client, prefix = login_contract_environment
    page = client.get(prefix + '/login')
    assert page.status_code == 200
    markup = SharedLoginMarkup(page.text)
    assert markup.root['data-session-url'] == prefix + '/login/session'
    assert markup.root['data-login-url'] == prefix + '/api/login'


@pytest.mark.parametrize('next_url', [None, '', '/kept?tab=one&sort=two', 'https://evil.example.test/'])
@pytest.mark.parametrize('surface', ['page', 'response'])
def test_login_default_next_matches_page_and_response(login_contract_environment, next_url, surface):
    _app, client, prefix = login_contract_environment
    params = {} if next_url is None else {'next': next_url}
    expected = next_url if next_url == '/kept?tab=one&sort=two' else prefix + '/'
    if surface == 'page':
        page = client.get(prefix + '/login', params=params)
        assert page.status_code == 200
        assert SharedLoginMarkup(page.text).root['data-next'] == expected
    else:
        response = client.post(prefix + '/api/login', json={
            'username': 'user@example.test', 'password': 'test-password', **params,
        })
        assert response.status_code == 200, response.text
        assert response.json()['next'] == expected


def test_official_login_js_http_sequence_reaches_workbench(login_contract_environment):
    _app, client, prefix = login_contract_environment
    page = client.get(prefix + '/login')
    assert page.status_code == 200
    markup = SharedLoginMarkup(page.text)
    for already_authenticated in (False, True):
        # ChatLogin 0.1.2 login.js: fresh bootstrap -> POST -> payload.next GET.
        bootstrap = client.get(markup.root['data-session-url'], follow_redirects=False)
        assert bootstrap.status_code == 200, bootstrap.text
        session = bootstrap.json()
        assert session['authenticated'] is already_authenticated
        headers = {'Content-Type': 'application/json'}
        if isinstance(session.get('csrf_token'), str):
            headers['X-CSRF-Token'] = session['csrf_token']
        response = client.post(markup.root['data-login-url'], headers=headers, json={
            'username': 'user@example.test', 'password': 'test-password',
            'next': markup.root['data-next'],
        }, follow_redirects=False)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload['next'] == prefix + '/'
        cookie = response.headers['set-cookie'].lower()
        assert 'httponly' in cookie and 'secure' in cookie and 'samesite=lax' in cookie
        workbench = client.get(payload['next'], follow_redirects=False)
        assert workbench.status_code == 200, workbench.text
        assert '<div id="root"></div>' in workbench.text
        assert './assets/todo-native.js' in workbench.text
        restored = client.get(prefix + '/api/session')
        assert restored.status_code == 200
        assert restored.json()['csrf_token'] == payload['csrf_token']


def test_auth_rejects_duplicate_origin_store_full_and_credential_rotation(tmp_path, monkeypatch):
    app, client = environment(tmp_path)
    duplicate = client.post('/api/login', json={'email': 'user@example.test', 'password': 'test-password'}, headers=[
        ('origin', 'https://todo.example.test'),
        ('origin', 'https://todo.example.test'),
    ])
    assert duplicate.status_code == 403

    module = importlib.import_module('chatsite.todo_web')
    auth_module = importlib.import_module('chatsite.todo_auth')
    class FullStore:
        def purge_expired(self, instance, now): pass
        def put(self, instance, digest, session, *, previous_digest=None):
            from chatlogin.sessions import StoreFull
            raise StoreFull('full')
        def get(self, instance, digest): return None
        def delete(self, instance, digest): pass
    monkeypatch.setattr(auth_module, 'SQLiteSessionStore', lambda *a, **k: FullStore())
    full_app = module.create_app(app.state.config, model_client=FakeModel())
    full_client = TestClient(full_app, base_url=app.state.config.public_url)
    full_client.headers['Origin'] = app.state.config.public_url
    assert full_client.post('/api/login', json={'email': 'user@example.test', 'password': 'test-password'}).status_code == 503

    monkeypatch.undo()
    old = login(client)
    cfg = TodoSettings.from_values({
        'CHATSITE_TODO_ADMIN_EMAIL': 'user@example.test',
        'CHATSITE_TODO_ADMIN_PASSWORD': 'rotated-password',
        'CHATSITE_TODO_API_BASE': 'https://api.example.test/v1',
        'CHATSITE_TODO_API_KEY': 'test-private-api-key',
        'CHATSITE_TODO_MODEL': 'test-model',
        'CHATSITE_TODO_PUBLIC_URL': 'https://todo.example.test',
        'CHATSITE_TODO_DATA_DIR': str(tmp_path / 'data'),
    })
    rotated = TestClient(module.create_app(cfg, model_client=FakeModel()), base_url=cfg.public_url)
    rotated.headers['Origin'] = cfg.public_url
    rotated.cookies.set('chattodo_session', old.cookies['chattodo_session'], domain='todo.example.test')
    assert rotated.get('/api/session').status_code == 401


def test_real_tcp_auth_service_chatlogin_flow(tmp_path):
    module = importlib.import_module('chatsite.todo_web')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base_url = f'http://127.0.0.1:{port}'
    cfg = TodoSettings.from_values({
        'CHATSITE_TODO_ADMIN_EMAIL': 'user@example.test',
        'CHATSITE_TODO_ADMIN_PASSWORD': 'test-password',
        'CHATSITE_TODO_API_BASE': 'https://api.example.test/v1',
        'CHATSITE_TODO_API_KEY': 'test-private-api-key',
        'CHATSITE_TODO_MODEL': 'test-model',
        'CHATSITE_TODO_PUBLIC_URL': base_url,
        'CHATSITE_TODO_DATA_DIR': str(tmp_path / 'data'),
        'CHATSITE_TODO_SECURE_COOKIE': 'false',
    })
    app = module.create_app(cfg, model_client=FakeModel())

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, lifespan='off', log_level='warning', access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.02)
        assert server.started
        with httpx.Client(base_url=base_url, headers={'Origin': base_url}, timeout=5) as client:
            assert client.get('/login').status_code == 200
            assert client.get('/login/assets/login.css').status_code == 200
            login_response = client.post('/api/login', json={'username': 'user@example.test', 'password': 'test-password', 'next': '/next'})
            assert login_response.status_code == 200, login_response.text
            payload = login_response.json()
            assert payload['email'] == 'user@example.test' and payload['next'] == '/next'
            assert 'httponly' in login_response.headers['set-cookie'].lower()
            assert client.get('/api/session').json()['csrf_token'] == payload['csrf_token']
            assert client.post('/api/boards', json={'title': 'bad'}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
            assert client.post('/api/logout', headers={'X-CSRF-Token': payload['csrf_token']}).status_code == 200
            assert client.get('/api/session').status_code == 401
    finally:
        server.should_exit = True
        thread.join(timeout=5)


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
    assert client.patch('/api/boards/' + board['id'] + '/view', json={'view': view, 'view_revision': board['view_revision']}).status_code == 200
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


def test_view_patch_requires_revision_and_rejects_delayed_stale_tab(tmp_path):
    _, client = environment(tmp_path)
    login(client)
    board = new_board(client)
    path = '/api/boards/' + board['id'] + '/view'
    assert client.patch(path, json={'view': {'zoom': 1.1}}).status_code == 400
    first = client.patch(path, json={'view_revision': 0, 'view': {'zoom': 1.2}})
    assert first.status_code == 200
    stale = client.patch(path, json={'view_revision': 0, 'view': {'zoom': 0.8}})
    assert stale.status_code == 409
    assert stale.json()['error']['code'] == 'view_revision_conflict'
    assert client.get('/api/boards/' + board['id']).json()['board']['view']['zoom'] == 1.2


def test_model_noop_reply_does_not_claim_tree_was_updated(tmp_path):
    fake = FakeModel(lambda args: [{
        'op': 'update', 'id': args['board']['nodes'][0]['id'],
        'fields': {'title': args['board']['nodes'][0]['title']},
    }])
    _, client = environment(tmp_path, fake)
    login(client)
    board = new_board(client)
    response = client.post('/api/boards/' + board['id'] + '/chat', json={
        'message': '保持现状', 'revision': board['revision'], 'request_id': str(uuid.uuid4()),
    })
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['change'] is None
    assert data['board']['revision'] == board['revision']
    assert not data['message']['content'].startswith('已更新任务树')
    assert data['message']['content'].startswith('任务树没有发生变化')


def test_delete_returns_committed_outcome_when_state_cleanup_fails(tmp_path, monkeypatch):
    app, client = environment(tmp_path)
    login(client)
    board = new_board(client)
    web = app.state.web_state
    original = web.complete_board_deletion
    monkeypatch.setattr(web, 'complete_board_deletion', lambda *_: (_ for _ in ()).throw(RuntimeError('cleanup failed')))
    payload = {'revision': board['revision'], 'confirm': True}
    first = client.request('DELETE', '/api/boards/' + board['id'], json=payload)
    assert first.status_code == 200, first.text
    assert first.json()['board_deleted'] is True
    assert first.json()['cleanup_pending'] is True
    assert client.get('/api/boards/' + board['id']).status_code == 404

    monkeypatch.setattr(web, 'complete_board_deletion', original)
    recovered = client.request('DELETE', '/api/boards/' + board['id'], json=payload)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()['cleanup_pending'] is False


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
