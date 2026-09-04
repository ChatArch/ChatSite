<div align="center">
    <a href="https://pypi.python.org/pypi/chatsite">
        <img src="https://img.shields.io/pypi/v/chatsite.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatSite/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatSite/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
    <a href="https://arch.gh.wzhecnu.cn/ChatSite/">
        <img src="https://img.shields.io/badge/docs-mkdocs-blue.svg" alt="Documentation" />
    </a>
</div>

<div align="center">

English | [简体中文](README.md)
</div>

# ChatSite

`ChatSite` is the web and service entry point for the ChatArch / Chat series. It starts from the template package shell: the CLI still exposes truthful root-level package information, while web features integrate Chat tool modules here. For example, the Overleaf editor is served by ChatSite and calls ChatOL as the Overleaf tool module. Future site capabilities must update Python APIs, service entry points, docs, and tests together.

## Quick Start

```bash
pip install chatsite
chatsite --version
chatsite --tree
chatsite --tree-brief
```

Development environment:

```bash
pip install -e ".[dev,docs]"
python -m pytest -q
mkdocs build --strict
python -m build
```

## CLI Tree

```text
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
└── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
```

The current public surface has root options only, so the full and brief trees are identical. When real commands gain parameters, `--tree` retains their signatures while `--tree-brief` omits them.

`chatsite hello` is not public CLI; it is a scaffold example leftover and must fail.

## Documentation

- Documentation home: https://arch.gh.wzhecnu.cn/ChatSite/
- CLI tree: https://arch.gh.wzhecnu.cn/ChatSite/cli-tree/
- English docs: https://arch.gh.wzhecnu.cn/ChatSite/en/

## Development Notes

Read `DEVELOP.md` and `AGENTS.md` before expanding commands, and keep `--tree`, `--tree-brief`, README, MkDocs, tests, and changelog synchronized.
