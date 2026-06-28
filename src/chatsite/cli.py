"""CLI entrypoint for chatsite."""

import click

from chatsite import __version__


@click.group()
@click.version_option(__version__, prog_name="chatsite")
def main() -> None:
    """chatsite command line interface."""
    # Add package-specific commands here. Prefer ChatStyle helpers for
    # interactive input when a command needs recoverable user input.


if __name__ == "__main__":
    main()
