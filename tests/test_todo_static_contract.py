"""Generated ChatTodo frontend contract; no server or model is required."""
from html.parser import HTMLParser
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/chatsite/todo_static"
FRONTEND = ROOT / "frontend/todo"


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.assets = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        if tag == "link" and values.get("href"):
            self.assets.append(values["href"])


def test_generated_entry_uses_prefix_safe_flat_assets():
    source = (STATIC / "index.html").read_text()
    page = Page(source)
    assert page.assets
    for url in page.assets:
        assert url.startswith("./assets/")
        name = url.removeprefix("./assets/")
        assert "/" not in name
        assert (STATIC / name).is_file()
    assert "<script>" not in source


def test_bundle_replaces_legacy_controller_and_has_no_source_maps():
    names = {path.name for path in STATIC.rglob("*") if path.is_file()}
    assert not {"app.js", "core.js", "style.css"} & names
    assert not any(name.endswith(".map") for name in names)
    assert 'todo-native.js' in names
    assert any(re.fullmatch(r"index-[A-Za-z0-9_-]+\.css", name) for name in names)


def test_formal_ui_excludes_candidate_a_and_private_material():
    text = "\n".join(
        path.read_text(errors="ignore")
        for path in STATIC.iterdir()
        if path.suffix in {".html", ".js", ".css"}
    ).lower()
    assert "chattodo" in text
    for forbidden in ("assistant-ui", "mind-elixir", "candidate", "/home/", "wzhecnu.cn"):
        assert forbidden not in text


def test_exact_b_only_dependency_root_and_build_contract():
    package = json.loads((FRONTEND / "package.json").read_text())
    assert package["dependencies"] == {
        "@ant-design/x": "2.9.0",
        "@ant-design/x-markdown": "2.9.0",
        "antd": "6.6.3",
        "react": "19.2.8",
        "react-dom": "19.2.8",
        "simple-mind-map": "0.14.0-fix.3",
    }
    lock = json.loads((FRONTEND / "package-lock.json").read_text())
    assert lock["packages"][""]["dependencies"] == package["dependencies"]
    assert "node_modules/mind-elixir" not in lock["packages"]
    assert not any(key.startswith("node_modules/@assistant-ui/") for key in lock["packages"])
    config = (FRONTEND / "vite.config.mjs").read_text()
    assert "assetsDir: ''" in config and "./assets/" in config


def test_licenses_and_bundled_cjk_font_are_retained():
    assert (STATIC / "THIRD_PARTY_NOTICES.txt").is_file()
    notices = (STATIC / "THIRD_PARTY_NOTICES.txt").read_text()
    assert "simple-mind-map" in notices
    assert "@ant-design/x" in notices
    assert (STATIC / "fonts/FONT-LICENSE.txt").is_file()
    assert list(STATIC.glob("*.woff2"))
