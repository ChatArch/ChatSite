"""Offline contracts for the Todo model adapter (only MockTransport)."""

import copy
import importlib
import importlib.util
import json

import httpx
import pytest


FAKE_KEY = "unit-test-key-not-a-credential"
BASE_URL = "https://provider.example.test/v1///"


def adapter():
    assert importlib.util.find_spec("chatsite.todo_model") is not None, (
        "The independent Todo model adapter must exist"
    )
    return importlib.import_module("chatsite.todo_model")


def node(node_id, parent_id=None, **fields):
    return {
        "id": node_id, "parent_id": parent_id, "title": "待办任务",
        "status": "pending", "body": "任务正文", "order": 0, **fields,
    }


@pytest.fixture
def board():
    return {
        "id": "board-a", "title": "当前任务树", "revision": 3,
        "nodes": [node("root"), node("selected", "root"),
                  node("child", "selected"), node("sibling", "root")],
        "view": {"private_ui_data": "not model context"},
    }


def proposal(operations=None):
    return {"message": "这是修改提案，不代表已执行。", "operations": operations or []}


def provider_response(protocol, value=None, *, text_only=False, response_id="resp-test"):
    text = json.dumps(proposal() if value is None else value, ensure_ascii=False)
    if protocol == "responses":
        output = [{"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": text},
        ]}] if text_only else [{
            "type": "function_call", "name": "todo_update",
            "call_id": "call-test", "arguments": text,
        }]
        return {"id": response_id, "status": "completed", "output": output}
    message = {"role": "assistant", "content": text} if text_only else {
        "role": "assistant", "content": None, "tool_calls": [{
            "id": "call-test", "type": "function", "function": {
                "name": "todo_update", "arguments": text,
            },
        }],
    }
    return {"id": "chatcmpl-test", "choices": [{
        "index": 0, "finish_reason": "stop" if text_only else "tool_calls",
        "message": message,
    }]}


def client_with_response(protocol, response, requests=None, **config):
    def handle(request):
        if requests is not None:
            requests.append(request)
        return response if isinstance(response, httpx.Response) else httpx.Response(200, json=response)

    return adapter().ModelClient(
        base_url=BASE_URL, api_key=FAKE_KEY, model="unit-test-model", protocol=protocol,
        transport=httpx.MockTransport(handle), **config,
    )


def generate(client, board, **kwargs):
    return client.generate(message="请只讨论选中分支", board=board, history=[], **kwargs)


def test_model_error_public_contract():
    error = adapter().ModelError("test_error", "安全提示")
    assert (error.code, error.message, error.status) == ("test_error", "安全提示", 502)
    assert str(error) == "安全提示"
    assert adapter().ModelError("bad_input", "无效输入", status=400).status == 400


@pytest.mark.parametrize("protocol,path", [
    ("responses", "/v1/responses"), ("chat_completions", "/v1/chat/completions"),
])
def test_protocol_payload_and_tool_result(protocol, path, board):
    requests = []
    operations = [{"op": "update", "id": "child", "fields": {"body": "新说明"}}]
    client = client_with_response(protocol, provider_response(protocol, proposal(operations)), requests)
    original = copy.deepcopy(board)
    history = [{"role": "user", "content": "先前仅作讨论"}]
    result = client.generate(
        message="修改说明", board=board, history=history, selected_node_id="selected",
        previous_response_id="resp-explicit",
    )
    assert result == {
        "content": proposal()["message"], "operations": operations,
        "response_id": "resp-test" if protocol == "responses" else None,
    }
    assert board == original
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == path
    assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in request.content.decode()
    assert request.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 90)
    payload = json.loads(request.content)
    assert payload["model"] == "unit-test-model"
    assert payload["stream"] is (protocol == "responses")
    if protocol == "responses":
        assert payload["store"] is False
    assert payload["parallel_tool_calls"] is False
    assert len(payload["tools"]) == 1
    if protocol == "responses":
        function = payload["tools"][0]
        assert "function" not in function
        assert function["type"] == "function"
        assert payload["tool_choice"] == "auto"
        assert payload["previous_response_id"] == "resp-explicit"
        context = json.loads(payload["input"][-1]["content"])
        prompt = payload["instructions"]
    else:
        assert "previous_response_id" not in payload
        assert payload["tools"][0]["type"] == "function"
        function = payload["tools"][0]["function"]
        assert payload["tool_choice"] == "auto"
        context = json.loads(payload["messages"][-1]["content"])
        prompt = payload["messages"][0]["content"]
    assert function["name"] == "todo_update"
    schema = function["parameters"]
    assert set(schema["required"]) == {"message", "operations"}
    variants = schema["properties"]["operations"]["items"]["oneOf"]
    shapes = {v["properties"]["op"]["const"]: set(v["required"]) for v in variants}
    assert shapes == {
        "create": {"op", "node"}, "update": {"op", "id", "fields"},
        "move": {"op", "id", "parent_id", "order"}, "delete": {"op", "id"},
    }
    assert all(v["additionalProperties"] is False for v in variants)
    assert context["message"] == "修改说明"
    assert context["board"]["id"] == "board-a"
    assert context["board"]["nodes"] == original["nodes"]
    assert "view" not in context["board"]
    assert context["selected_node_id"] == "selected"
    assert context["history"] == history
    for rule in ("数据", "最新用户请求", "选中", "精确 ID", "碰撞", "pending", "执行证据", "讨论", "确认"):
        assert rule in prompt


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_json_text_is_displayed_without_becoming_a_tool_call(protocol, board):
    result = generate(client_with_response(protocol, provider_response(protocol, text_only=True)), board)
    assert result["content"] == json.dumps(proposal(), ensure_ascii=False)
    assert result["operations"] == []


def test_previous_response_id_is_explicit_and_never_cached(board):
    requests = []
    client = client_with_response("responses", provider_response("responses"), requests, timeout=12)
    generate(client, board, previous_response_id="resp-board-a")
    other = {**board, "id": "board-b", "title": "另一棵树"}
    generate(client, other)
    generate(client, other, previous_response_id="resp-board-b")
    bodies = [json.loads(request.content) for request in requests]
    assert bodies[0]["previous_response_id"] == "resp-board-a"
    assert "previous_response_id" not in bodies[1]
    assert bodies[2]["previous_response_id"] == "resp-board-b"
    assert all(request.extensions["timeout"]["read"] == 12 for request in requests)
    assert all("board-a" not in json.loads(body["input"][-1]["content"])["board"]["id"] for body in bodies[1:])


@pytest.mark.parametrize("field,value", [
    ("base_url", ""), ("base_url", None), ("api_key", ""), ("api_key", "  "),
    ("model", ""), ("model", None),
])
def test_missing_configuration_fails_without_mock_success(field, value):
    config = {"base_url": BASE_URL, "api_key": FAKE_KEY, "model": "test-model"}
    config[field] = value
    with pytest.raises(adapter().ModelError) as caught:
        adapter().ModelClient(**config, transport=httpx.MockTransport(lambda request: pytest.fail("No request allowed")))
    assert (caught.value.code, caught.value.status) == ("model_not_configured", 503)
    assert FAKE_KEY not in str(caught.value)


@pytest.mark.parametrize("changes", [
    {"protocol": "auto"}, {"protocol": "chat"}, {"protocol": None},
    {"base_url": "file:///model"}, {"base_url": "https://user:secret@provider.example.test"},
    {"base_url": "https://provider.example.test?key=secret"},
    {"base_url": "https://provider.example.test/#secret"}, {"base_url": "not-a-url"},
    {"timeout": None}, {"timeout": 0}, {"timeout": -1}, {"timeout": True},
    {"timeout": float("inf")}, {"timeout": float("nan")},
    {"api_key": "bad\nheader"}, {"model": ["bad"]},
])
def test_invalid_configuration_is_safe(changes):
    config = {"base_url": BASE_URL, "api_key": FAKE_KEY, "model": "test-model", **changes}
    with pytest.raises(adapter().ModelError) as caught:
        adapter().ModelClient(**config, transport=httpx.MockTransport(lambda request: pytest.fail("No request allowed")))
    assert (caught.value.code, caught.value.status) == ("invalid_model_config", 503)
    assert "secret" not in str(caught.value)
    assert BASE_URL not in str(caught.value)


BAD_PROPOSALS = [
    [], None, "text", 1, True, {}, {"message": "ok"}, {"operations": []},
    {"message": "", "operations": []}, {"message": "  ", "operations": []},
    {"message": [], "operations": []}, {"message": "ok", "operations": {}},
    {"message": "ok", "operations": [], "shell": "not-a-tool"},
    {"message": "ok", "operations": [None]},
    {"message": "ok", "operations": [{"op": "shell", "command": "not-a-tool"}]},
    {"message": "ok", "operations": [{"op": ["delete"], "id": "child"}]},
    {"message": "ok", "operations": [{"op": "delete", "id": 1}]},
    {"message": "ok", "operations": [{"op": "delete", "id": ""}]},
    {"message": "ok", "operations": [{"op": "delete", "id": "child", "extra": True}]},
    {"message": "ok", "operations": [{"op": "update", "id": "child", "fields": {}}]},
    {"message": "ok", "operations": [{"op": "update", "id": "child", "fields": []}]},
    {"message": "ok", "operations": [{"op": "update", "id": "child", "fields": {"parent_id": "sibling"}}]},
    {"message": "ok", "operations": [{"op": "update", "id": "child", "fields": {"id": "other"}}]},
    {"message": "ok", "operations": [{"op": "update", "id": "child", "fields": {"status": "done"}}]},
    {"message": "ok", "operations": [{"op": "update", "id": "child", "fields": {"body": {}}}]},
    {"message": "ok", "operations": [{"op": "update", "id": "child", "fields": {"order": True}}]},
    {"message": "ok", "operations": [{"op": "move", "id": "child", "parent_id": [], "order": 0}]},
    {"message": "ok", "operations": [{"op": "move", "id": "child", "parent_id": "selected"}]},
    {"message": "ok", "operations": [{"op": "create", "node": {"title": "missing id"}}]},
    {"message": "ok", "operations": [{"op": "create", "node": node("new", "selected", body=12)}]},
    {"message": "ok", "operations": [{"op": "create", "node": node("new", "selected", extra=True)}]},
]


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("value", BAD_PROPOSALS)
def test_proposal_shape_is_validated_independently(protocol, value, board):
    response = provider_response(protocol)
    # Explicit None must remain JSON null, not the helper's default value.
    arguments = json.dumps(value)
    if protocol == "responses":
        response["output"][0]["arguments"] = arguments
    else:
        response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
    with pytest.raises(adapter().ModelError) as caught:
        generate(client_with_response(protocol, response), board)
    assert (caught.value.code, caught.value.status) == ("invalid_model_response", 502)


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("problem", ["unknown_tool", "multiple_calls", "arguments_object", "bad_json", "duplicate_keys"])
def test_bad_tool_envelope_never_succeeds(protocol, problem, board):
    response = provider_response(protocol)
    calls = response["output"] if protocol == "responses" else response["choices"][0]["message"]["tool_calls"]
    function = calls[0] if protocol == "responses" else calls[0]["function"]
    if problem == "unknown_tool":
        function["name"] = "browser"
    elif problem == "multiple_calls":
        calls.append(copy.deepcopy(calls[0]))
    elif problem == "arguments_object":
        function["arguments"] = proposal()
    elif problem == "bad_json":
        function["arguments"] = f"not JSON {FAKE_KEY}"
    else:
        function["arguments"] = '{"message":"ok","operations":[{"op":"delete","id":"sibling","id":"child"}]}'
    with pytest.raises(adapter().ModelError) as caught:
        generate(client_with_response(protocol, response), board)
    assert caught.value.code == "invalid_model_response"
    assert FAKE_KEY not in str(caught.value)


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("response", [None, [], "text", {}, {"output": []}, {"choices": []}])
def test_bad_provider_envelopes_are_safe_errors(protocol, response, board):
    with pytest.raises(adapter().ModelError) as caught:
        generate(client_with_response(protocol, httpx.Response(200, json=response)), board)
    assert caught.value.code == "invalid_model_response"


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("text", ["", " "])
def test_empty_plain_responses_remain_rejected(protocol, text, board):
    response = provider_response(protocol, text_only=True)
    if protocol == "responses":
        response["output"][0]["content"][0]["text"] = text
    else:
        response["choices"][0]["message"]["content"] = text
    with pytest.raises(adapter().ModelError) as caught:
        generate(client_with_response(protocol, response), board)
    assert caught.value.code == "invalid_model_response"


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("text", ["你好，先讨论思路。", "```python\nprint('example')\n```", '{"message":"delete","operations":[{"op":"delete","id":"root"}]}', '{broken', '[]', '```json\n{"operations":[]}\n```'])
def test_plain_assistant_conversation_has_no_operations(protocol, text, board):
    response = provider_response(protocol, text_only=True)
    if protocol == "responses":
        response["output"][0]["content"][0]["text"] = text
    else:
        response["choices"][0]["message"]["content"] = text
    result = generate(client_with_response(protocol, response), board)
    assert result["content"] == text
    assert result["operations"] == []


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_oversized_reply_is_rejected_before_any_mutation(protocol, board):
    response = provider_response(protocol, {"message": "x" * 65536, "operations": []})
    with pytest.raises(adapter().ModelError):
        generate(client_with_response(protocol, response), board)


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_incomplete_or_refused_outputs_do_not_apply_partial_changes(protocol, board):
    response = provider_response(protocol)
    if protocol == "responses":
        response["status"] = "incomplete"
    else:
        response["choices"][0]["finish_reason"] = "length"
    with pytest.raises(adapter().ModelError) as caught:
        generate(client_with_response(protocol, response), board)
    assert caught.value.code == "invalid_model_response"


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("status,code,public_status", [
    (401, "model_auth_error", 502), (403, "model_auth_error", 502),
    (429, "model_rate_limited", 429), (500, "model_http_error", 502),
    (302, "model_http_error", 502),
])
def test_http_errors_have_no_provider_details_or_retry(protocol, status, code, public_status, board, caplog):
    requests = []
    response = httpx.Response(status, text=f"provider-body-secret {FAKE_KEY} {BASE_URL}", headers={
        "location": "https://other.example.test/another-billing-channel",
    })
    client = client_with_response(protocol, response, requests)
    with pytest.raises(adapter().ModelError) as caught:
        generate(client, board)
    assert len(requests) == 1
    assert (caught.value.code, caught.value.status) == (code, public_status)
    for secret in (FAKE_KEY, BASE_URL, "provider-body-secret"):
        assert secret not in str(caught.value)
        assert secret not in repr(caught.value)
        assert secret not in caplog.text
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("failure,code,status", [
    (httpx.ReadTimeout, "model_timeout", 504), (httpx.ConnectTimeout, "model_timeout", 504),
    (httpx.ConnectError, "model_unavailable", 502), (httpx.RemoteProtocolError, "model_unavailable", 502),
])
def test_network_failures_are_safe_without_retry(failure, code, status, board):
    requests = []
    def handle(request):
        requests.append(request)
        raise failure(f"{FAKE_KEY} {BASE_URL}", request=request)
    client = adapter().ModelClient(
        base_url=BASE_URL, api_key=FAKE_KEY, model="test-model", transport=httpx.MockTransport(handle),
    )
    with pytest.raises(adapter().ModelError) as caught:
        generate(client, board)
    assert len(requests) == 1
    assert (caught.value.code, caught.value.status) == (code, status)
    assert FAKE_KEY not in str(caught.value)
    assert BASE_URL not in str(caught.value)
    assert caught.value.__suppress_context__


class CountingStream(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    def close(self):
        self.closed = True


@pytest.mark.parametrize("declared_length", [None, "1", str(2 * 1024 * 1024 + 1)])
def test_response_is_capped_during_streaming(declared_length, board):
    module = adapter()
    assert module.MAX_RESPONSE_BYTES == 2 * 1024 * 1024
    stream = CountingStream([b"x" * 65536] * 40)
    headers = {} if declared_length is None else {"content-length": declared_length}
    client = client_with_response("responses", httpx.Response(200, headers=headers, stream=stream))
    with pytest.raises(module.ModelError) as caught:
        generate(client, board)
    assert (caught.value.code, caught.value.status) == ("model_response_too_large", 502)
    assert stream.closed
    assert stream.reads < 40
    if declared_length and int(declared_length) > module.MAX_RESPONSE_BYTES:
        assert stream.reads == 0


def test_history_and_node_bodies_are_bounded_data(board):
    module = adapter()
    requests = []
    board["nodes"][0]["body"] = "文" * (module.MAX_NODE_BODY_CHARS + 100)
    history = [{"role": "user", "content": f"old-{i}"} for i in range(module.MAX_HISTORY_MESSAGES + 2)]
    history[-1] = {"role": "assistant", "content": "a" * (module.MAX_HISTORY_CHARS + 100), "private": "omit"}
    original = copy.deepcopy((board, history))
    client = client_with_response("responses", provider_response("responses"), requests)
    client.generate(message="继续讨论", board=board, history=history)
    context = json.loads(json.loads(requests[0].content)["input"][0]["content"])
    assert len(context["history"]) == module.MAX_HISTORY_MESSAGES
    assert context["history"][0]["content"] == "old-2"
    assert len(context["history"][-1]["content"]) <= module.MAX_HISTORY_CHARS
    assert module.TRUNCATION_MARKER in context["history"][-1]["content"]
    assert "private" not in context["history"][-1]
    assert len(context["board"]["nodes"][0]["body"]) <= module.MAX_NODE_BODY_CHARS
    assert module.TRUNCATION_MARKER in context["board"]["nodes"][0]["body"]
    assert (board, history) == original


@pytest.mark.parametrize("changes", [
    {"message": ""}, {"message": []}, {"board": []}, {"board": {"nodes": {}}},
    {"history": {}}, {"history": [{"role": "system", "content": "escalate me"}]},
    {"history": [{"role": "user", "content": []}]}, {"selected_node_id": 1},
    {"previous_response_id": []}, {"previous_response_id": ""},
])
def test_invalid_input_fails_before_transport(changes, board):
    config = {"message": "讨论", "board": board, "history": [], **changes}
    client = adapter().ModelClient(
        base_url=BASE_URL, api_key=FAKE_KEY, model="test-model",
        transport=httpx.MockTransport(lambda request: pytest.fail("Invalid input must not be sent")),
    )
    with pytest.raises(adapter().ModelError) as caught:
        client.generate(**config)
    assert (caught.value.code, caught.value.status) == ("invalid_model_input", 400)


@pytest.mark.parametrize("oversized", ["message", "nodes", "request"])
def test_excessive_input_is_rejected_before_transport(oversized, board):
    module = adapter()
    message = "讨论"
    if oversized == "message":
        message = "文" * (module.MAX_MESSAGE_CHARS + 1)
    elif oversized == "nodes":
        board["nodes"] = [node(f"n-{i}") for i in range(module.MAX_NODES + 1)]
    else:
        board["nodes"] = [node(f"n-{i}", body="文" * module.MAX_NODE_BODY_CHARS) for i in range(200)]
    client = adapter().ModelClient(
        base_url=BASE_URL, api_key=FAKE_KEY, model="test-model",
        transport=httpx.MockTransport(lambda request: pytest.fail("Oversized input must not be sent")),
    )
    with pytest.raises(module.ModelError) as caught:
        client.generate(message=message, board=board, history=[])
    assert (caught.value.code, caught.value.status) == ("model_input_too_large", 413)
