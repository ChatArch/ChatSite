"""CLI entrypoint for chatsite."""

from __future__ import annotations

import click
from chatstyle import add_tree_option

from chatsite import __version__


@click.group(
    name="chatsite",
    invoke_without_command=True,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="chatsite")
@add_tree_option()
def main() -> None:
    """ChatArch 网站与服务入口。"""


@main.group()
def todo() -> None:
    """任务树工作台。"""


@todo.command()
@click.option("--host", default=None, help="覆盖监听地址。")
@click.option("--port", type=click.IntRange(1, 65535), default=None, help="覆盖监听端口。")
@click.option("--profile", default=None, help="使用命名 ChatEnv profile。")
@click.option("--home", type=click.Path(file_okay=False), default=None, help="ChatArch home。")
def serve(host, port, profile, home):
    """启动任务树 Web 服务。"""
    from chatsite.todo_web import main as run_web
    args = []
    for name, value in (("host", host), ("port", port), ("profile", profile), ("home", home)):
        if value is not None:
            args.extend(["--" + name, str(value)])
    try:
        run_web(args)
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from None


@todo.command()
@click.option("--profile", default=None, help="使用命名 ChatEnv profile。")
@click.option("--home", type=click.Path(file_okay=False), default=None, help="ChatArch home。")
def check(profile, home):
    """验证配置及模型，会发送一次不修改任务的小请求。"""
    from chatsite.todo_config import TodoSettings, probe_model
    try:
        probe_model(TodoSettings.from_profile(profile, home=home))
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None


@main.group()
def image() -> None:
    """ChatImg 文生图服务。"""


@image.command(name="serve")
@click.option("--host", default=None, help="覆盖监听地址。")
@click.option("--port", type=click.IntRange(1, 65535), default=None, help="覆盖监听端口。")
@click.option("--profile", default=None, help="使用命名 ChatEnv profile。")
@click.option("--home", type=click.Path(file_okay=False), default=None, help="ChatArch home。")
def serve_image(host, port, profile, home):
    """启动 ChatImg Web 服务。"""
    from chatsite.image_web import main as run_web
    args = []
    for name, value in (("host", host), ("port", port), ("profile", profile), ("home", home)):
        if value is not None:
            args.extend(["--" + name, str(value)])
    try:
        run_web(args)
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from None


@image.command(name="check")
@click.option("--profile", default=None, help="使用命名 ChatEnv profile。")
@click.option("--home", type=click.Path(file_okay=False), default=None, help="ChatArch home。")
def check_image(profile, home):
    """验证 Image 配置，不发起图片生成。"""
    from chatsite.image_config import ImageSettings
    try:
        cfg = ImageSettings.from_profile(profile, home=home)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(f"ChatSite Image 配置已加载：{cfg.public_url}")


if __name__ == "__main__":
    main()
