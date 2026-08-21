from pathlib import Path

from click.testing import CliRunner

from chatsite.cli import main


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependency_and_provider_contracts():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"click>=8.0,<9.0"' in pyproject
    assert '"chatstyle>=0.2.0,<0.3.0"' in pyproject
    assert '"chatenv>=0.2.10,<0.3.0"' in pyproject
    assert '[project.entry-points."chatenv.configs"]' in pyproject
    assert 'chatsite = "chatsite.config"' in pyproject


def test_checked_in_cli_trees_match_registered_runtime_output():
    full = CliRunner().invoke(main, ["--tree"])
    brief = CliRunner().invoke(main, ["--tree-brief"])

    assert full.exit_code == 0
    assert brief.exit_code == 0
    assert full.output == brief.output
    tree_block = f"```text\n{full.output}```"
    for relative_path in (
        "README.md",
        "README.en.md",
        "docs/cli-tree.md",
        "docs/cli-tree.en.md",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert tree_block in text
