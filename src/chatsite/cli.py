"""CLI entrypoint for chatsite."""

from __future__ import annotations

import inspect
from typing import cast

import click

from chatsite import __version__


def _purpose(command: click.Command) -> str:
    text = command.short_help or inspect.getdoc(command.callback) or ""
    return " ".join(text.strip().split()).rstrip(".")


def _render_cli_tree(root: click.Group) -> str:
    """Render the CLI tree from the registered Click command surface."""

    children = [(name, command) for name, command in root.commands.items() if not command.hidden]
    lines = [f"chatsite  # {_purpose(root)}"]
    root_entries = [
        ("--help", "show command help"),
        ("--version", "show the installed package version"),
        ("--tree", "show this CLI tree"),
    ]
    for index, (option, purpose) in enumerate(root_entries):
        connector = "└──" if not children and index == len(root_entries) - 1 else "├──"
        lines.append(f"{connector} {option}  # {purpose}")
    for index, (name, command) in enumerate(children):
        connector = "└──" if index == len(children) - 1 else "├──"
        lines.append(f"{connector} {name}  # {_purpose(command)}")
    return "\n".join(lines)


@click.group(
    name="chatsite",
    invoke_without_command=True,
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="chatsite")
@click.option("--tree", "show_tree", is_flag=True, is_eager=True, help="Show this CLI tree.")
@click.pass_context
def main(ctx: click.Context, show_tree: bool) -> None:
    """ChatSite package scaffold for site workflows."""

    if show_tree:
        click.echo(_render_cli_tree(cast(click.Group, ctx.command)))
        ctx.exit(0)


if __name__ == "__main__":
    main()
