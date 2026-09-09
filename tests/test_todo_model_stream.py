import json
import httpx
import pytest
from chatsite.todo_model import ModelClient, ModelError


def final_response():
    return {"id": "resp-test", "status": "completed", "output": [{"type": "function_call", "name": "todo_update", "arguments": json.dumps({"message": "连接成功", "operations": []})}]}


def run(body, check=None):
    def handle(request):
        if check:
            check(json.loads(request.content))
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})
    client = ModelClient(base_url="https://example.test/v1", api_key="test-key", model="test", transport=httpx.MockTransport(handle))
    return client.generate(message="检查连接", board={"nodes": [{"id": "root", "parent_id": None, "title": "任务"}]}, history=[])


def test_responses_requires_stream_and_no_provider_storage():
    def check(payload):
        assert payload["stream"] is True
        assert payload["store"] is False
    data = "event: response.completed\ndata: " + json.dumps({"type": "response.completed", "response": final_response()}) + "\n\ndata: [DONE]\n\n"
    assert run(data, check)["content"] == "连接成功"


@pytest.mark.parametrize("body", [
    'data: {"type":"response.created"}\n\n',
    'data: {"type":"response.failed","response":{"error":{"message":"private-provider-detail"}}}\n\n',
    'data: not-json\n\n',
])
def test_incomplete_or_failed_stream_never_becomes_a_success(body):
    with pytest.raises(ModelError) as caught:
        run(body)
    assert "private-provider-detail" not in str(caught.value)




def test_terminal_items_rebuild_empty_completed_footer():
    full = final_response()
    item = {"type": "response.output_item.done", "output_index": 0, "item": full["output"][0]}
    footer = {"type": "response.completed", "response": {"id": "resp-test", "status": "completed", "output": []}}
    data = "data: " + json.dumps(item) + "\n\ndata: " + json.dumps(footer) + "\n\n"
    assert run(data)["content"] == "连接成功"


def test_two_completed_responses_are_rejected():
    event = "data: " + json.dumps({"type": "response.completed", "response": final_response()}) + "\n\n"
    with pytest.raises(ModelError):
        run(event + event)
