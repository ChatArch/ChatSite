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

`ChatSite` is the web and service entry point for the ChatArch / Chat series. The root web app is a feature hub, and feature workspaces call package-specific Chat tool modules behind the shared ChatSite login/session layer. For example, the Overleaf editor is served by ChatSite and calls ChatOL as the Overleaf tool module. Future site capabilities must update Python APIs, service entry points, docs, and tests together.

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

Command names and signatures follow the live registered tree; annotations are translated below.

```text
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
└── todo  # Task-tree workbench.
    ├── check [--profile PROFILE] [--home HOME]  # Check configuration and send one no-edit model request.
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # Start the task-tree Web service.
```

The public surface now includes Todo service commands. `--tree` retains parameter signatures while `--tree-brief` omits them.

`chatsite hello` is not public CLI; it is a scaffold example leftover and must fail.

## Documentation

- Documentation home: https://arch.gh.wzhecnu.cn/ChatSite/
- CLI tree: https://arch.gh.wzhecnu.cn/ChatSite/cli-tree/
- English docs: https://arch.gh.wzhecnu.cn/ChatSite/en/

## Development Notes

Read `DEVELOP.md` and `AGENTS.md` before expanding commands, and keep `--tree`, `--tree-brief`, README, MkDocs, tests, and changelog synchronized.


## Todo workbench

The Todo workbench uses SimpleMindMap for native map editing and Ant Design X for conversations, while ChatTodo retains ownership of nodes, revisions, receipts and undo. The login page and browser sessions use the shared ChatLogin core; task data remains in ChatTodo/ChatSite Todo storage. Install `"ChatSite[todo]>=0.1.5,<0.2.0"` and run `chatsite todo serve` or `chatsite todo check`; the Python package includes the frontend and needs no Node runtime. To maintain UI source, run `npm ci --ignore-scripts`, `npm test`, and `npm run build` in `frontend/todo/` and commit the generated assets.

The `chatsite-todo` ChatEnv provider owns configuration. Responses and Chat Completions are supported; Plan providers retain their explicit Plan endpoint without pay-as-you-go fallback. See [workbench usage](docs/todo-workbench.md) and [data integration](docs/todo-data-integration.md).
