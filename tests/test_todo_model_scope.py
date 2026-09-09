import pytest

import chatsite.todo_model as model


def board():
    return {'id': 'board', 'revision': 0, 'title': '任务', 'nodes': [
        {'id': 'root', 'parent_id': None, 'title': '总任务', 'status': 'pending', 'body': '', 'order': 0},
        {'id': 'inside', 'parent_id': 'root', 'title': '范围内', 'status': 'pending', 'body': '', 'order': 0},
        {'id': 'leaf', 'parent_id': 'inside', 'title': '叶子', 'status': 'pending', 'body': '', 'order': 0},
        {'id': 'outside', 'parent_id': 'root', 'title': '范围外', 'status': 'pending', 'body': '', 'order': 1},
    ]}


def test_scope_api_exists():
    assert hasattr(model, 'enforce_scope') and hasattr(model, 'requires_confirmation')


def test_scope_allows_descendant_and_new_parent_chain():
    operations = [
        {'op': 'create', 'node': {'id': 'new-child', 'parent_id': 'new-parent', 'title': '子任务'}},
        {'op': 'create', 'node': {'id': 'new-parent', 'parent_id': 'inside', 'title': '父任务'}},
        {'op': 'update', 'id': 'leaf', 'fields': {'title': '修改'}},
    ]
    assert model.enforce_scope(operations, board(), 'inside') is None
    assert model.enforce_scope([{'op': 'delete', 'id': 'outside'}], board(), None) is None


@pytest.mark.parametrize('operations', [
    [{'op': 'update', 'id': 'outside', 'fields': {'title': '越界'}}],
    [{'op': 'delete', 'id': 'outside'}],
    [{'op': 'move', 'id': 'leaf', 'parent_id': 'outside', 'order': 0}],
    [{'op': 'move', 'id': 'outside', 'parent_id': 'inside', 'order': 0}],
    [{'op': 'create', 'node': {'id': 'new', 'parent_id': 'outside', 'title': '越界'}}],
    [{'op': 'create', 'node': {'id': 'new', 'parent_id': None, 'title': '越界'}}],
    [{'op': 'create', 'node': {'id': 'new-a', 'parent_id': 'new-b', 'title': '环'}}, {'op': 'create', 'node': {'id': 'new-b', 'parent_id': 'new-a', 'title': '环'}}],
])
def test_scope_rejects_outside_branch(operations):
    with pytest.raises(model.ModelError):
        model.enforce_scope(operations, board(), 'inside')


def test_missing_selection_and_replacement_of_truncated_document_rejected():
    with pytest.raises(model.ModelError):
        model.enforce_scope([], board(), 'missing')
    state = board()
    state['nodes'][2]['body'] = 'x' * (model.MAX_NODE_BODY_CHARS + 1)
    with pytest.raises(model.ModelError):
        model.enforce_scope([{'op': 'update', 'id': 'leaf', 'fields': {'body': 'lost suffix'}}], state, 'inside')


@pytest.mark.parametrize('operation,expected', [
    ({'op': 'delete', 'id': 'leaf'}, True),
    ({'op': 'move', 'id': 'leaf', 'parent_id': 'root', 'order': 0}, True),
    ({'op': 'update', 'id': 'leaf', 'fields': {'status': 'completed'}}, True),
    ({'op': 'update', 'id': 'leaf', 'fields': {'status': 'cancelled'}}, True),
    ({'op': 'create', 'node': {'id': 'new', 'parent_id': 'root', 'title': '新增', 'status': 'completed'}}, True),
    ({'op': 'update', 'id': 'leaf', 'fields': {'title': '新标题'}}, False),
    ({'op': 'create', 'node': {'id': 'new', 'parent_id': 'root', 'title': '新增'}}, False),
])
def test_confirmation_is_computed_locally(operation, expected):
    assert model.requires_confirmation([operation], board()['nodes']) is expected
