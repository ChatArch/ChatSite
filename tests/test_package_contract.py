from pathlib import Path
import re

from click.testing import CliRunner

from chatsite.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependency_and_provider_contracts():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"click>=8.0,<9.0"' in pyproject
    assert '"chatstyle>=0.2.0,<0.3.0"' in pyproject
    assert '"chatenv>=0.2.10,<0.3.0"' in pyproject
    assert '"ChatLogin[web]>=0.1.2,<0.2.0"' in pyproject
    assert '[project.entry-points."chatenv.configs"]' in pyproject
    assert 'chatsite = "chatsite.config"' in pyproject


def test_checked_in_cli_trees_match_registered_runtime_output():
    full = CliRunner().invoke(main, ["--tree"])
    brief = CliRunner().invoke(main, ["--tree-brief"])

    assert full.exit_code == 0
    assert brief.exit_code == 0
    assert full.output != brief.output
    assert "[--profile PROFILE]" in full.output
    assert "[--profile PROFILE]" not in brief.output
    assert "todo" in full.output and "todo" in brief.output
    tree_block = f"```text\n{full.output}```"
    for relative_path in (
        "README.md",
        "README.en.md",
        "docs/cli-tree.md",
        "docs/cli-tree.en.md",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        if relative_path.endswith('.en.md'):
            blocks = re.findall(r'```text\n(chatsite\n.*?)```', text, flags=re.S)
            assert len(blocks) == 1
            # Localization may translate annotations, never commands/signatures/hierarchy.
            signature = lambda value: [line.split(' # ', 1)[0].rstrip() for line in value.splitlines()]
            assert signature(blocks[0]) == signature(full.output)
            assert not re.search(r'[\u4e00-\u9fff]', blocks[0])
        else:
            assert tree_block in text
