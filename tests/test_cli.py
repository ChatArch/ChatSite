import click
from click.testing import CliRunner

from chatsite import __version__
from chatsite.cli import main

EXPECTED_FULL_TREE = """\
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── image  # ChatImg 文生图服务。
│   ├── check [--profile PROFILE] [--home HOME]  # 验证 Image 配置，不发起图片生成。
│   └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动 ChatImg Web 服务。
└── todo  # 任务树工作台。
    ├── check [--profile PROFILE] [--home HOME]  # 验证配置及模型，会发送一次不修改任务的小请求。
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动任务树 Web 服务。
"""
EXPECTED_BRIEF_TREE = EXPECTED_FULL_TREE.replace(
    "check [--profile PROFILE] [--home HOME]", "check"
).replace("serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]", "serve")


def test_version_option_reports_package_version():
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert f"chatsite, version {__version__}" in result.output


def test_top_level_help_exposes_shared_tree_options_and_not_scaffold_hello():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "--tree" in result.output
    assert "--tree-brief" in result.output
    assert "hello" not in result.output.lower()


def test_tree_option_renders_registered_todo_surface():
    result = CliRunner().invoke(main, ["--tree"])
    assert result.exit_code == 0
    assert result.output == EXPECTED_FULL_TREE
    assert "hello" not in result.output.lower()


def test_tree_brief_renders_registered_todo_surface():
    result = CliRunner().invoke(main, ["--tree-brief"])
    assert result.exit_code == 0
    assert result.output == EXPECTED_BRIEF_TREE


def test_registered_command_signatures_are_omitted_only_in_brief_tree():
    @click.command(help="Preview a site without publishing.")
    @click.argument("target")
    def preview(target: str) -> None:
        del target
    main.add_command(preview)
    try:
        full = CliRunner().invoke(main, ["--tree"])
        brief = CliRunner().invoke(main, ["--tree-brief"])
    finally:
        main.commands.pop("preview", None)
    assert full.exit_code == 0
    assert "preview <TARGET>  # Preview a site without publishing." in full.output
    assert brief.exit_code == 0
    assert "preview  # Preview a site without publishing." in brief.output
    assert "<TARGET>" not in brief.output


def test_scaffold_hello_command_is_not_public():
    result = CliRunner().invoke(main, ["hello", "ChatArch"])
    assert result.exit_code != 0
    assert "No such command" in result.output
