<div align="center">
    <a href="https://pypi.python.org/pypi/chatsite">
        <img src="https://img.shields.io/pypi/v/chatsite.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/chatsite/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/chatsite/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
</div>

<div align="center">

[English](README.en.md) | [简体中文](README.md)
</div>

# chatsite

ChatSite package scaffold.

## Quick Start

```bash
pip install -e ".[dev]"
chatsite --help
chatsite --version
python -m pytest -q
python -m build
```

## CLI Contract

This template depends on `chatstyle>=0.1.0,<0.2.0` and `chatenv>=0.2.0,<0.3.0`. New commands should prefer:

- `CommandSchema` / `CommandField` for inputs.
- `add_interactive_option()` for the shared `-i/-I` switch.
- `resolve_command_inputs()` for missing args, defaults, TTY behavior, and validation.
- Generate `config.py` and a `chatenv.configs` entry point by default so the package is ChatEnv-discoverable; use `--without-chatenv-provider` only when ChatEnv integration is intentionally not needed.

## Layout

- `src/`: package source code
- `tests/code-tests/`: code tests and migrated historical tests
- `tests/cli-tests/`: real CLI tests, doc-first
- `tests/mock-cli-tests/`: mock/fake CLI tests, doc-first

## Development Notes

See `DEVELOP.md` and `AGENTS.md` before expanding the scaffold.
