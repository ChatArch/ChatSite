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

[英文版](README.en.md) | 简体中文
</div>

# ChatSite

`ChatSite` 是 ChatArch / Chat 系列的 Web 与 service 入口。根 Web 应用是功能 hub，各功能工作区通过共享的 ChatSite 登录/session 层调用具体的 Chat 工具模块；例如 Overleaf 编辑器由 ChatSite serve，并调用 ChatOL 作为 Overleaf 工具模块。后续新增站点能力时，必须同步 Python API、服务入口、文档和测试。

## 快速开始

```bash
pip install chatsite
chatsite --version
chatsite --tree
chatsite --tree-brief
```

开发环境：

```bash
pip install -e ".[dev,docs]"
python -m pytest -q
mkdocs build --strict
python -m build
```

## CLI 树

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

当前公开接口包含 Todo 服务命令；`--tree` 保留参数签名，`--tree-brief` 省略签名。

`chatsite hello` 不是公开 CLI；它属于脚手架示例残留，必须失败。

## 文档

- 文档首页：https://arch.gh.wzhecnu.cn/ChatSite/
- CLI 树：https://arch.gh.wzhecnu.cn/ChatSite/cli-tree/
- 英文文档：https://arch.gh.wzhecnu.cn/ChatSite/en/

## 开发说明

扩展命令前先阅读 `DEVELOP.md` 和 `AGENTS.md`，并保持 `--tree`、`--tree-brief`、README、MkDocs、测试与 changelog 同步。


## Todo 任务树工作台

Todo 工作台提供独立多画布、标题优先的思维导图、右／上／下新增、原地标题编辑与可选 Markdown 详情、模型对话、持久化和撤销。手机支持双指缩放与平移。Web 由 ChatSite 提供，任务领域由 ChatTodo 提供；`pip install 'ChatSite[todo]'` 会安装兼容的领域包和服务依赖。

- [工作台使用与验收](docs/todo-workbench.md)
- [数据存储与模块接入](docs/todo-data-integration.md)：数据库、Node/Board/View、并发／幂等、Python/HTTP 与备份。

使用 `chatsite todo serve` 启动，`chatsite todo check` 验证配置和模型。配置由 ChatEnv 的 `chatsite-todo` provider 管理。模型支持 Responses／Chat Completions；使用 Plan 服务时应保留其 Plan 专属入口，不自动回退到按量计费。
