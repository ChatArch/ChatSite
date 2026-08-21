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
    """ChatSite package scaffold for site workflows."""


if __name__ == "__main__":
    main()
