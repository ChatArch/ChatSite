"""Review regressions for archive metadata and cookie-write origin authority."""
import json
from http.server import ThreadingHTTPServer
import threading
import urllib.error
import urllib.request

import pytest
from chatlogin import ManagedUsers

from chatsite.hosting import HostingError, HostingStore, make_archive
from chatsite.hosting_client import NoRedirect
from chatsite.hosting_web import HostingApp, decorate_handler
from chatsite.web import AppConfig, DataStore, make_handler


@pytest.mark.parametrize('metadata', ['.hg/store/data', '.svn/wc.db', '.bzr/repository/data', '_darcs/hashed_inventory', 'CVS/Entries', '.jj/repo/store', '.GIT/config'])
def test_client_archive_rejects_repository_metadata(tmp_path, metadata):
    (tmp_path / 'index.html').write_text('hello')
    target = tmp_path / metadata
    target.parent.mkdir(parents=True)
    target.write_text('private repository contents')
    with pytest.raises(HostingError):
        make_archive(tmp_path)


def test_cookie_writes_require_origin_but_bearer_clients_do_not(tmp_path, monkeypatch):
    monkeypatch.delenv('CHATSITE_HOSTING_ENABLED', raising=False)
    monkeypatch.setenv('CHATSITE_WEB_ADMIN_EMAIL', 'owner@example.test')
    monkeypatch.setenv('CHATSITE_WEB_ADMIN_PASSWORD', 'owner-password')
    monkeypatch.setenv('CHATSITE_WEB_PUBLIC_URL', 'http://127.0.0.1')
    config = AppConfig.from_env(data_dir=str(tmp_path / 'hub'))
    native = make_handler(config, DataStore(config))
    native.log_message = lambda *args: None
    users = ManagedUsers.in_memory('hosting-origin-test')
    record = users.bootstrap_owner('owner@example.test', 'owner-password')
    actor = users.authenticate(record.username, 'owner-password')
    app = HostingApp(HostingStore(tmp_path / 'hosting', users), origin=config.public_url, native_owner=actor)
    server = ThreadingHTTPServer(('127.0.0.1', 0), decorate_handler(native, app))
    origin = f'http://127.0.0.1:{server.server_port}'
    app.origin = origin
    native.config = AppConfig(**{**config.__dict__, 'public_url': origin, 'allowed_origins': frozenset([origin])})
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    opener = urllib.request.build_opener(NoRedirect())

    def post(path, payload, headers):
        request = urllib.request.Request(origin + path, data=json.dumps(payload).encode(),
                                         headers={'Content-Type': 'application/json', **headers})
        try:
            response = opener.open(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, response.read()

    try:
        credentials = {'username': record.username, 'password': 'owner-password'}
        for missing_origin in [{}, {'Origin': ''}, {'Origin': 'null'}]:
            code, _, _ = post('/api/hosting/login', credentials, missing_origin)
            assert code == 403
        code, headers, body = post('/api/hosting/login', credentials, {'Origin': origin})
        assert code == 200
        cookie = headers['Set-Cookie'].split(';', 1)[0]
        csrf = json.loads(body)['csrf_token']
        cookie_auth = {'Cookie': cookie, 'X-CSRF-Token': csrf}
        for missing_origin in [{}, {'Origin': ''}, {'Origin': 'null'}]:
            code, _, _ = post('/api/hosting/sites', {'slug': 'denied', 'title': 'Denied'}, {**cookie_auth, **missing_origin})
            assert code == 403
        assert app.store.list_sites(actor) == []
        code, _, _ = post('/api/hosting/sites', {'slug': 'allowed', 'title': 'Allowed'}, {**cookie_auth, 'Origin': origin})
        assert code == 201
        # Explicit CLI clients can authenticate and write without browser Origin.
        code, _, body = post('/api/hosting/login', credentials, {'X-ChatSite-Client': 'cli'})
        assert code == 200
        bearer = {'Authorization': 'Bearer ' + json.loads(body)['token']}
        code, _, _ = post('/api/hosting/sites', {'slug': 'cli-site', 'title': 'CLI'}, bearer)
        assert code == 201
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        users.close()
