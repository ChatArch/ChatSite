import json
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading
import urllib.error
import urllib.request

from click.testing import CliRunner
from chatlogin import ManagedUsers

from chatsite.cli import main
from chatsite.hosting import HostingStore
from chatsite.hosting_client import HostingClient, NoRedirect
from chatsite.hosting_web import HostingApp, decorate_handler
from chatsite.web import AppConfig, DataStore, make_handler


def test_real_http_cli_workflow_nested_mime_and_security(tmp_path, monkeypatch):
    monkeypatch.delenv('CHATSITE_HOSTING_ENABLED', raising=False)
    monkeypatch.setenv('CHATSITE_WEB_ADMIN_EMAIL', 'owner@example.test')
    monkeypatch.setenv('CHATSITE_WEB_ADMIN_PASSWORD', 'owner-password')
    monkeypatch.setenv('CHATSITE_WEB_PUBLIC_URL', 'http://127.0.0.1')
    config = AppConfig.from_env(data_dir=str(tmp_path / 'hub'))
    native = make_handler(config, DataStore(config))
    native.log_message = lambda *args: None
    users = ManagedUsers.in_memory('hosting-http')
    record = users.bootstrap_owner('owner@example.test', 'owner-password')
    owner = users.authenticate(record.username, 'owner-password')
    app = HostingApp(HostingStore(tmp_path / 'hosting', users), origin='http://127.0.0.1', native_owner=owner)
    server = ThreadingHTTPServer(('127.0.0.1', 0), decorate_handler(native, app))
    origin = f'http://127.0.0.1:{server.server_port}'
    app.origin = origin
    native.config = AppConfig(**{**config.__dict__, 'public_url': origin, 'allowed_origins': frozenset([origin])})
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    runner = CliRunner()
    home = tmp_path / 'client-home'
    anonymous = urllib.request.build_opener(NoRedirect())

    def fetch(path, *, data=None, headers=None):
        try:
            response = anonymous.open(urllib.request.Request(origin + path, data=data, headers=headers or {}))
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    def cli(*args, profile='default', ok=True, env=None):
        result = runner.invoke(main, ['hosting', '--home', str(home), '--profile', profile, *args], env=env)
        assert (result.exit_code == 0) is ok, result.output
        assert 'owner-password' not in result.output and 'member-password' not in result.output
        return json.loads(result.output) if ok else result.output

    try:
        assert fetch('/api/hosting/sites')[0] == 401
        assert fetch('/api/hosting/register', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': origin})[0] == 403
        cli('login', '--url', origin, '--username', 'owner@example.test', '--password-env', 'HOSTING_TEST_PASSWORD', env={'HOSTING_TEST_PASSWORD': 'owner-password'})
        assert cli('whoami')['role'] == 'owner'
        user = cli('users', 'create', 'member@example.test', '--password-env', 'HOSTING_TEST_PASSWORD', env={'HOSTING_TEST_PASSWORD': 'member-password'})
        cli('create', 'first', '--title', 'First', '--alias', 'notes')
        cli('create', 'second', '--title', 'Second')
        cli('login', '--url', origin, '--username', 'member@example.test', '--password-env', 'HOSTING_TEST_PASSWORD', profile='member', env={'HOSTING_TEST_PASSWORD': 'member-password'})
        source = tmp_path / 'dist'
        source.mkdir()
        (source / 'index.html').write_text('<h1>version-A</h1>')
        (source / 'nested').mkdir()
        (source / 'nested/index.html').write_text('<h1>nested index</h1>')
        cli('upload', 'second', str(source), profile='member', ok=False)
        cli('create', 'forbidden', profile='member', ok=False)
        cli('users', 'list', profile='member', ok=False)
        cli('grant', 'second', '--user-id', user['user_id'], '--role', 'publisher')
        a = cli('upload', 'second', str(source), profile='member')
        owner_client = HostingClient.from_profile(home=home)
        member_client = HostingClient.from_profile('member', home=home)
        bearer = {'Authorization': 'Bearer ' + member_client.token}
        assert fetch('/sites/second/dev/index.html', headers=bearer)[2] == b'<h1>version-A</h1>'
        code, headers, body = fetch('/sites/second/dev/nested/', headers=bearer)
        assert code == 200 and headers['Content-Type'].startswith('text/html') and b'nested index' in body
        assert 'sandbox' in headers['Content-Security-Policy'] and 'allow-same-origin' not in headers['Content-Security-Policy']
        assert fetch('/sites/second/prod/', headers=bearer)[0] == 404
        cli('publish', 'second', '--release', a['id'], profile='member', ok=False)
        cli('publish', 'second', '--release', a['id'], '--yes', profile='member')
        (source / 'index.html').write_text('<h1>version-B</h1>')
        b = cli('upload', 'second', str(source), profile='member')
        assert b'version-A' in fetch('/sites/second/prod/', headers=bearer)[2]
        assert b'version-B' in fetch('/sites/second/dev/', headers=bearer)[2]
        cli('rollback', 'second', '--release', b['id'], '--yes', profile='member', ok=False)
        cli('publish', 'second', '--release', b['id'], '--yes', profile='member')
        cli('rollback', 'second', '--release', a['id'], '--yes', profile='member')
        assert b'version-A' in fetch('/sites/second/prod/', headers=bearer)[2]
        assert b'version-B' in fetch('/sites/second/dev/', headers=bearer)[2]
        assert fetch('/sites/first/prod/', headers=bearer)[0] == 403
        first = cli('upload', 'first', str(source))
        cli('publish', 'first', '--release', first['id'], '--yes')
        owner_header = {'Authorization': 'Bearer ' + owner_client.token}
        for prefix in ['/notes/', '/sites/first/prod/']:
            code, headers, body = fetch(prefix + 'nested/', headers=owner_header)
            assert code == 200 and headers['Content-Type'].startswith('text/html') and b'nested index' in body
            code, headers, body = fetch(prefix + 'nested', headers=owner_header)
            assert code == 303 and headers['Location'] == prefix + 'nested/'
        assert fetch('/notes/')[0] == 303
        # A cookie login must supply CSRF and a permitted Origin for writes.
        code, headers, raw = fetch('/api/hosting/login', data=json.dumps({'username': record.username, 'password': 'owner-password'}).encode(), headers={'Content-Type': 'application/json', 'Origin': origin})
        assert code == 200
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        csrf = json.loads(raw)['csrf_token']
        cookie_headers = {'Cookie': cookie, 'Origin': origin, 'Content-Type': 'application/json'}
        assert fetch('/api/hosting/sites', data=b'{}', headers=cookie_headers)[0] == 403
        cookie_headers['X-CSRF-Token'] = csrf
        cookie_headers['Origin'] = 'https://untrusted.example.test'
        assert fetch('/api/hosting/sites', data=b'{}', headers=cookie_headers)[0] == 403
        cookie_headers['Origin'] = origin
        assert fetch('/api/hosting/sites', data=b'{}', headers=cookie_headers)[0] == 400
        cli('grant', 'second', '--user-id', user['user_id'], '--role', 'none')
        assert fetch('/sites/second/prod/', headers=bearer)[0] == 403
        cli('users', 'disable', user['user_id'])
        cli('whoami', profile='member', ok=False)
        cli('logout')
        cli('whoami', ok=False)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        users.close()
