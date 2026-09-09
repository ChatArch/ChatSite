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

```text
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
└── todo  # 任务树工作台。
    ├── check [--profile PROFILE] [--home HOME]  # 验证配置及模型，会发送一次不修改任务的小请求。
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动任务树 Web 服务。
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

The Todo workbench provides named canvases, title-first brainstorming, three-direction node creation, inline titles, optional Markdown details, isolated model conversations and undo. Touch devices support pinch zoom and pan. Install `ChatSite[todo]` for compatible domain and service dependencies; run `chatsite todo serve` or `chatsite todo check`. The `chatsite-todo` ChatEnv provider owns configuration. Responses and Chat Completions are supported; Plan providers retain their explicit Plan endpoint without pay-as-you-go fallback.
