"""Regression tests for real SQLite layout/write/deletion lifecycles."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading

import pytest
from chatsite.todo_state import WebState, StateError
from test_todo_web import environment, login, new_board


def rows(app, board_id=None):
    with app.state.web_state.connection() as db:
        if board_id is None:
            return db.execute('SELECT count(*) FROM presentations').fetchone()[0]
        return db.execute('SELECT count(*) FROM presentations WHERE board_id=?', (board_id,)).fetchone()[0]


def test_late_patch_does_not_recreate_deleted_board_layout(tmp_path, monkeypatch):
    import chatsite.todo_web as module
    app, client = environment(tmp_path)
    login(client)
    board = new_board(client)
    path = '/api/boards/' + board['id']
    entered, release = threading.Event(), threading.Event()
    original = module._body

    async def delayed(request):
        result = await original(request)
        if request.url.path.endswith('/presentation'):
            entered.set()
            await asyncio.to_thread(release.wait, 5)
        return result

    monkeypatch.setattr(module, '_body', delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.patch, path + '/presentation', json={'layout': 'mindMap', 'revision': 0})
        try:
            assert entered.wait(3)
            assert client.request('DELETE', path, json={'revision': board['revision'], 'confirm': True}).status_code == 200
        finally:
            release.set()
        response = pending.result(timeout=5)
    assert response.status_code == 404
    assert rows(app, board['id']) == 0


def test_layout_write_rejects_completed_deletion_but_not_prepared(tmp_path):
    state = WebState(tmp_path / 'web.sqlite3')
    state.prepare_board_deletion('owner', 'board')
    assert state.save_presentation('owner', 'board', 'mindMap', 0)['revision'] == 1
    state.complete_board_deletion('owner', 'board')
    with pytest.raises(StateError) as error:
        state.save_presentation('owner', 'board', 'mindMap', 0)
    assert error.value.status == 404
    assert state.presentation('owner', 'board')['revision'] == 0


def test_repeat_delete_repairs_legacy_late_layout_row(tmp_path):
    app, client = environment(tmp_path)
    login(client)
    board = new_board(client)
    path = '/api/boards/' + board['id']
    body = {'revision': board['revision'], 'confirm': True}
    assert client.request('DELETE', path, json=body).status_code == 200
    with app.state.web_state.connection() as db:
        db.execute('INSERT INTO presentations VALUES(?,?,?,?)', ('user@example.test', board['id'], 'mindMap', 1))
    result = client.request('DELETE', path, json=body)
    assert result.status_code == 200 and result.json()['cleanup_pending'] is False
    assert rows(app, board['id']) == 0


def test_completed_cleanup_creates_its_own_tombstone(tmp_path):
    state = WebState(tmp_path / 'web.sqlite3')
    state.complete_board_deletion('owner', 'board')
    with state.connection() as db:
        row = db.execute('SELECT state FROM board_deletions WHERE owner=? AND board_id=?', ('owner', 'board')).fetchone()
    assert row is not None and row['state'] == 'complete'


def trigger_failure(app):
    with app.state.web_state.connection() as db:
        db.execute("CREATE TRIGGER reject_layout BEFORE INSERT ON presentations BEGIN SELECT RAISE(ABORT, 'injected presentation failure'); END")


def import_payload():
    return {'board': {'title': 'rollback fixture', 'nodes': [{'id': 'root', 'parent_id': None, 'title': 'root', 'status': 'pending', 'body': '', 'order': 0}], 'presentation': {'layout': 'mindMap'}}}


def test_sqlite_import_failure_compensates_new_board(tmp_path):
    app, client = environment(tmp_path)
    login(client)
    trigger_failure(app)
    response = None
    try:
        response = client.post('/api/import', json=import_payload())
    except sqlite3.IntegrityError:
        pass  # The old code rethrows the real SQLite failure through TestClient.
    assert client.get('/api/boards').json()['boards'] == []
    assert rows(app) == 0
    assert response is not None and response.status_code == 500
    assert response.json()['error']['code'] == 'import_storage_error'


def test_import_rollback_accepts_an_already_deleted_board(tmp_path, monkeypatch):
    app, client = environment(tmp_path)
    login(client)
    original = app.state.web_state.save_presentation

    def concurrent_delete(owner, board_id, layout, revision):
        current = app.state.boards.get(board_id, owner)
        app.state.web_state.prepare_board_deletion(owner, board_id)
        app.state.boards.delete(board_id, owner, current['revision'], confirm=True)
        app.state.web_state.complete_board_deletion(owner, board_id)
        return original(owner, board_id, layout, revision)

    monkeypatch.setattr(app.state.web_state, 'save_presentation', concurrent_delete)
    response = client.post('/api/import', json=import_payload())
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'not_found'
    assert client.get('/api/boards').json()['boards'] == []
    assert rows(app) == 0


def test_failed_domain_rollback_does_not_erase_concurrent_changes(tmp_path, monkeypatch):
    app, client = environment(tmp_path)
    login(client)
    trigger_failure(app)
    original = app.state.web_state.save_presentation

    def concurrent_change(owner, board_id, layout, revision):
        current = app.state.boards.get(board_id, owner)
        app.state.boards.mutate(board_id, owner, current['revision'], 'concurrent-fixture',
                               [{'op': 'update', 'id': 'root', 'fields': {'title': 'concurrent edit'}}])
        return original(owner, board_id, layout, revision)

    monkeypatch.setattr(app.state.web_state, 'save_presentation', concurrent_change)
    response = None
    try:
        response = client.post('/api/import', json=import_payload())
    except sqlite3.IntegrityError:
        pass
    assert response is not None and response.status_code == 500
    assert response.json()['error']['code'] == 'import_rollback_pending'
    board_id = client.get('/api/boards').json()['boards'][0]['id']
    board = client.get('/api/boards/' + board_id).json()['board']
    assert board['nodes'][0]['title'] == 'concurrent edit'
    with app.state.web_state.connection() as db:
        assert db.execute('SELECT state FROM board_deletions WHERE board_id=?', (board_id,)).fetchone()['state'] == 'prepared'
    response = client.request('DELETE', '/api/boards/' + board_id, json={'revision': board['revision'], 'confirm': True})
    assert response.status_code == 200


def test_failed_import_cleanup_has_explicit_recoverable_receipt(tmp_path, monkeypatch):
    app, client = environment(tmp_path)
    login(client)
    trigger_failure(app)
    original = app.state.web_state.complete_board_deletion
    monkeypatch.setattr(app.state.web_state, 'complete_board_deletion', lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError('injected cleanup failure')))
    response = None
    try:
        response = client.post('/api/import', json=import_payload())
    except sqlite3.IntegrityError:
        pass
    assert client.get('/api/boards').json()['boards'] == []
    assert response is not None and response.status_code == 500
    assert response.json()['error']['code'] == 'import_cleanup_pending'
    with app.state.web_state.connection() as db:
        receipt = dict(db.execute('SELECT * FROM board_deletions').fetchone())
    assert receipt['state'] == 'prepared'
    assert receipt['board_id'] in response.json()['error']['message']
    monkeypatch.setattr(app.state.web_state, 'complete_board_deletion', original)
    result = client.request('DELETE', '/api/boards/' + receipt['board_id'], json={'revision': 0, 'confirm': True})
    assert result.status_code == 200 and result.json()['cleanup_pending'] is False
    assert rows(app) == 0
