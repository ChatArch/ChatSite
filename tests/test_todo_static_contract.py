"""ChatTodo 静态入口的离线安全契约，不依赖后端或模型。"""
from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "src/chatsite/todo_static"


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_entry_and_complete_controls_exist():
    assert (ROOT / "index.html").is_file(), "必须提供真实工作台入口"
    page = Page((ROOT / "index.html").read_text())
    ids = {attrs.get("id") for _, attrs in page.tags}
    assert {
        "login-form", "login-email", "login-password", "board-select", "new-board",
        "canvas", "scene", "nodes", "edges", "add-button", "zoom-in", "zoom-out", "fit",
        "detail", "detail-bar", "detail-close", "node-title-input", "node-status-input",
        "node-body-input", "node-preview", "save-node", "move-node", "delete-node",
        "chat-toggle", "chat-hide", "chat-input", "chat-form", "messages", "scope-all",
        "undo", "history", "export-board", "import-board", "delete-board", "save-status",
        "conflict-panel", "conflict-refresh", "conflict-rebase", "modal", "logout",
    } <= ids


def test_csp_and_local_asset_contract():
    assert (ROOT / "index.html").exists()
    source = (ROOT / "index.html").read_text()
    page = Page(source)
    for tag, attrs in page.tags:
        assert not any(k.lower().startswith("on") for k in attrs), attrs
        if tag == "script":
            assert attrs.get("src", "").startswith("/assets/")
        if tag in {"link", "script"}:
            url = attrs.get("href", attrs.get("src", ""))
            assert url.startswith("/assets/")
            assert (ROOT / url.removeprefix("/assets/")).is_file()
    assert "<script>" not in source
    assert "localStorage" not in (ROOT / "app.js").read_text()
    assert "sessionStorage" not in (ROOT / "app.js").read_text()


def test_no_prototype_data_or_private_machine_paths():
    assert (ROOT / "app.js").exists()
    for name in ("app.js", "core.js", "index.html", "style.css"):
        source = (ROOT / name).read_text()
        assert not re.search(r"/(?:home|Users)/[A-Za-z0-9_-]+/", source)
        assert not re.search(r"https?://(?:localhost|127\.0\.0\.1|[^\s'\"]+\.wzhecnu\.cn)", source)
        assert not any(text in source for text in ("示例对话", "刷新即重置", "设计原型", "保存到原型"))


def test_safe_markdown_and_dom_only_untrusted_content():
    assert (ROOT / "core.js").exists()
    core = (ROOT / "core.js").read_text()
    app = (ROOT / "app.js").read_text()
    assert "DOMPurify.sanitize" in core
    assert "RETURN_DOM_FRAGMENT" in core
    assert "marked.parse" in core
    assert not re.search(r"\.(?:innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", app + core)
    assert "X-CSRF-Token" in core and 'credentials: "same-origin"' in core
    assert "crypto.randomUUID()" in core
    assert (ROOT / "vendor/README.md").exists()
    assert (ROOT / "vendor/marked-LICENSE.md").exists()
    assert (ROOT / "vendor/dompurify-LICENSE.txt").exists()


def test_business_state_and_view_safety_contract():
    assert (ROOT / "app.js").exists()
    source = (ROOT / "app.js").read_text()
    for text in ("beforeunload", "visibilitychange", "pointercancel", "request_id", "confirm_destructive", "proposal_id", "base_revision", "selected_node_id", "view_revision"):
        assert text in source
    assert "409" in source and "401" in source
    assert (ROOT / "fonts/FONT-LICENSE.txt").exists()
