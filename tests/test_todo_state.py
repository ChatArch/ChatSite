import importlib
import importlib.util
import sqlite3
import stat

import pytest


def module():
    assert importlib.util.find_spec('chatsite.todo_state') is not None
    return importlib.import_module('chatsite.todo_state')


def store(tmp_path):
    return module().WebState(tmp_path / 'private' / 'web.sqlite3', session_ttl=3600)


def test_sessions_are_hashed_persistent_and_revocable(tmp_path):
    state = store(tmp_path)
    session = state.create_session('user@example.test')
    assert session['csrf_token'] != session['token']
    assert state.session(session['token'])['email'] == 'user@example.test'
    assert state.session('wrong') is None
    assert state.check_csrf(session['token'], session['csrf_token'])
    assert not state.check_csrf(session['token'], 'wrong')
    rows = sqlite3.connect(state.path).execute('select token_hash from sessions').fetchall()
    assert session['token'] not in str(rows)
    assert stat.S_IMODE(state.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state.path.parent.stat().st_mode) == 0o700
    second = module().WebState(state.path)
    assert second.session(session['token'])
    second.logout(session['token'])
    assert state.session(session['token']) is None


def test_expired_session_is_rejected(tmp_path, monkeypatch):
    m = module()
    now = [1000.0]
    monkeypatch.setattr(m.time, 'time', lambda: now[0])
    state = m.WebState(tmp_path / 'private/web.sqlite3', session_ttl=10)
    session = state.create_session('user@example.test')
    now[0] += 11
    assert state.session(session['token']) is None


def test_login_throttle_is_bounded_and_clearable(tmp_path):
    state = store(tmp_path)
    for _ in range(8):
        state.login_failure('test-client')
    assert not state.login_allowed('test-client')
    assert state.login_allowed('another-client')
    state.clear_login_failures('test-client')
    assert state.login_allowed('test-client')


def test_conversations_are_isolated_and_messages_persist(tmp_path):
    state = store(tmp_path)
    a = state.conversation('owner', 'board-a')
    b = state.conversation('owner', 'board-b')
    c = state.conversation('other', 'board-a')
    assert len({a['id'], b['id'], c['id']}) == 3
    state.add_message('owner', 'board-a', 'user', '创建任务', request_id='request-a')
    state.add_message('owner', 'board-a', 'user', '创建任务', request_id='request-a')
    assert len(state.messages('owner', 'board-a')) == 1
    assert state.messages('other', 'board-a') == []
    assert state.messages('owner', 'board-b') == []


def test_chat_requests_are_bound_to_payload_and_cache_generation(tmp_path):
    m = module()
    state = store(tmp_path)
    payload = dict(message='创建任务', revision=1, selected_node_id=None)
    first = state.begin_chat('owner', 'board', 'req', payload)
    assert first['state'] == 'new'
    with pytest.raises(m.StateError) as exc:
        state.begin_chat('owner', 'board', 'req', payload)
    assert exc.value.status == 409
    with pytest.raises(m.StateError):
        state.begin_chat('owner', 'board', 'req', {**payload, 'message': 'other'})
    generation = dict(content='提议', operations=[], response_id='response-a')
    state.save_generation('owner', 'board', 'req', generation)
    assert state.begin_chat('owner', 'board', 'req', payload)['result'] == generation
    result = {'message': {'role': 'assistant', 'content': '提议'}, 'change': None}
    state.finish_chat('owner', 'board', 'req', result, response_id='response-a')
    cached = state.begin_chat('owner', 'board', 'req', payload)
    assert cached['state'] == 'done' and cached['result'] == result
    assert state.conversation('owner', 'board')['response_id'] == 'response-a'
    assert state.conversation('owner', 'other')['response_id'] is None


def test_only_one_model_request_per_board(tmp_path):
    m = module()
    state = store(tmp_path)
    state.begin_chat('owner', 'board', 'first', {'message': 'a'})
    with pytest.raises(m.StateError):
        state.begin_chat('owner', 'board', 'second', {'message': 'b'})
    state.finish_chat('owner', 'board', 'first', {'error': {'code': 'failed'}}, status=502)
    assert state.begin_chat('owner', 'board', 'second', {'message': 'b'})['state'] == 'new'


def test_proposals_are_owner_bound_and_messages_show_applied_receipt(tmp_path):
    m = module()
    state = store(tmp_path)
    proposal = state.create_proposal('owner', 'board', 'req', 2, [{'op': 'delete', 'id': 'child'}], '删除子任务', 'root')
    again = state.create_proposal('owner', 'board', 'req', 2, [{'op': 'delete', 'id': 'child'}], '删除子任务', 'root')
    assert proposal['id'] == again['id']
    with pytest.raises(m.StateError) as exc:
        state.proposal('other', 'board', proposal['id'])
    assert exc.value.status == 404
    state.add_message('owner', 'board', 'assistant', '等待确认', proposal=proposal, request_id='req')
    result = {'change': {'id': 'change-1'}, 'board': {'revision': 3}}
    state.finish_proposal('owner', 'board', proposal['id'], result)
    assert state.proposal('owner', 'board', proposal['id'])['applied']
    message = state.messages('owner', 'board')[0]
    assert message['proposal'] is None and message['change']['id'] == 'change-1'


def test_board_deletion_receipt_survives_until_cleanup_completes(tmp_path):
    state = store(tmp_path)
    state.add_message('owner', 'board', 'user', 'private draft')
    first = state.prepare_board_deletion('owner', 'board')
    assert first['state'] == 'prepared' and first['existing'] is False
    assert module().WebState(state.path).prepare_board_deletion('owner', 'board')['existing'] is True

    state.complete_board_deletion('owner', 'board')
    assert state.prepare_board_deletion('owner', 'board')['state'] == 'complete'
    assert state.messages('owner', 'board') == []


def test_symlink_database_is_rejected(tmp_path):
    target = tmp_path / 'target'
    target.write_text('do not overwrite')
    link = tmp_path / 'link.sqlite3'
    link.symlink_to(target)
    with pytest.raises(ValueError):
        module().WebState(link)
    assert target.read_text() == 'do not overwrite'
