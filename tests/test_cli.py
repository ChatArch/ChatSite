import click
from click.testing import CliRunner

from chatsite import __version__
from chatsite.cli import main

EXPECTED_FULL_TREE = 'chatsite\n├── --help  # Show this message and exit.\n├── --version  # Show the version and exit.\n├── --tree  # Print the registered CLI tree and exit.\n├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.\n├── hosting [--profile PROFILE] [--home HOME]  # Upload dev sites, publish reviewed versions, and manage site access.\n│   ├── bootstrap [--username USERNAME] [--password-env PASSWORD-ENV]  # Server operator only: create the first hosting owner in an empty account directory.\n│   ├── create <SITE> [--title TITLE] [--owner OWNER] [--alias ALIAS] [--trusted]  # Administrator: register a private site, with isolated scripts by default.\n│   ├── grant <SITE> [--user-id USER-ID] [--role ROLE]  # Administrator: grant or revoke access to one private site.\n│   ├── login [--url URL] [--username USERNAME] [--password-env PASSWORD-ENV]  # Sign in with an administrator-provisioned account; save a private session.\n│   ├── logout  # Revoke this CLI session on the server.\n│   ├── publish <SITE> [--release RELEASE] [--yes]  # Publish an explicitly selected version to production.\n│   ├── rollback <SITE> [--release RELEASE] [--yes]  # Restore a previously published production version; dev is unchanged.\n│   ├── sites  # List sites this account may read.\n│   ├── upload <SITE> <DIRECTORY>  # Upload a static directory to dev; production is unchanged.\n│   ├── users  # Administrator account provisioning; public registration stays closed.\n│   │   ├── create <USERNAME> [--password-env PASSWORD-ENV] [--role ROLE]  # Create an account; the password is never printed or stored in the repository.\n│   │   ├── disable <USER-ID>  # Disable a user and revoke all of their hosting sessions.\n│   │   └── list  # List safe account metadata.\n│   ├── versions <SITE>  # List immutable versions for a site.\n│   └── whoami  # Show the current account without session or CSRF values.\n├── image  # ChatImg 文生图服务。\n│   ├── check [--profile PROFILE] [--home HOME]  # 验证 Image 配置，不发起图片生成。\n│   └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动 ChatImg Web 服务。\n└── todo  # 任务树工作台。\n    ├── check [--profile PROFILE] [--home HOME]  # 验证配置及模型，会发送一次不修改任务的小请求。\n    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动任务树 Web 服务。\n'
EXPECTED_BRIEF_TREE = 'chatsite\n├── --help  # Show this message and exit.\n├── --version  # Show the version and exit.\n├── --tree  # Print the registered CLI tree and exit.\n├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.\n├── hosting  # Upload dev sites, publish reviewed versions, and manage site access.\n│   ├── bootstrap  # Server operator only: create the first hosting owner in an empty account directory.\n│   ├── create  # Administrator: register a private site, with isolated scripts by default.\n│   ├── grant  # Administrator: grant or revoke access to one private site.\n│   ├── login  # Sign in with an administrator-provisioned account; save a private session.\n│   ├── logout  # Revoke this CLI session on the server.\n│   ├── publish  # Publish an explicitly selected version to production.\n│   ├── rollback  # Restore a previously published production version; dev is unchanged.\n│   ├── sites  # List sites this account may read.\n│   ├── upload  # Upload a static directory to dev; production is unchanged.\n│   ├── users  # Administrator account provisioning; public registration stays closed.\n│   │   ├── create  # Create an account; the password is never printed or stored in the repository.\n│   │   ├── disable  # Disable a user and revoke all of their hosting sessions.\n│   │   └── list  # List safe account metadata.\n│   ├── versions  # List immutable versions for a site.\n│   └── whoami  # Show the current account without session or CSRF values.\n├── image  # ChatImg 文生图服务。\n│   ├── check  # 验证 Image 配置，不发起图片生成。\n│   └── serve  # 启动 ChatImg Web 服务。\n└── todo  # 任务树工作台。\n    ├── check  # 验证配置及模型，会发送一次不修改任务的小请求。\n    └── serve  # 启动任务树 Web 服务。\n'


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
