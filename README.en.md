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
├── image  # ChatImg image generation service.
│   ├── check [--profile PROFILE] [--home HOME]  # Validate Image configuration without generating an image.
│   └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # Start the ChatImg Web service.
└── todo  # Task-tree workbench.
    ├── check [--profile PROFILE] [--home HOME]  # Check configuration and send one no-edit model request.
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # Start the task-tree Web service.
```

The public surface now includes Todo and Image service commands. `--tree` retains parameter signatures while `--tree-brief` omits them.

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

## Overleaf / Hub Web

Install `"ChatSite[overleaf]>=0.1.5,<0.2.0"` and run `chatsite-web`. The Hub and `/overleaf` are standard-library HTTP services that use ChatLogin's UI-only shared `/login`, `/login/session`, and login assets; browser mutations carry the shared CSRF token. The existing `chatsite.sqlite3` remains authoritative for Settings, Overleaf credentials/session, OpenAI key, conversations, and messages. Login sessions move to a separate `auth.sqlite3`, so older local session cookies need a fresh sign-in.

## ChatImg image service

Install `"ChatSite[image-web]>=0.1.5,<0.2.0"` and run `chatsite image serve`. The root page remains public: guests can still use `/api/generate`, `/generated/<filename>`, `/api/images/<filename>`, preview, download, and share. Login is optional; successful authenticated generations are stored in the current account's own SQLite history. Guests cannot enumerate global history, and old anonymous images are not reassigned to a user.

The `chatsite-image` ChatEnv provider owns host configuration. Runtime data defaults to `~/.chatarch/chatsite/image/`. Model credentials stay in the ChatImg/OpenAI profile; ChatSite does not copy API keys. `CHATSITE_IMAGE_LEGACY_GENERATED_DIR` can expose old anonymous files read-only for URL compatibility. The migration plan is to mount the old directory read-only, audit access and lifecycle needs, then copy or archive only after a separate operations approval; the default service does not move, delete, or claim legacy files.
