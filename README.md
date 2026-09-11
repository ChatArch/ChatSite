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
├── image  # ChatImg 文生图服务。
│   ├── check [--profile PROFILE] [--home HOME]  # 验证 Image 配置，不发起图片生成。
│   └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动 ChatImg Web 服务。
└── todo  # 任务树工作台。
    ├── check [--profile PROFILE] [--home HOME]  # 验证配置及模型，会发送一次不修改任务的小请求。
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动任务树 Web 服务。
```

当前公开接口包含 Todo 与 Image 服务命令；`--tree` 保留参数签名，`--tree-brief` 省略签名。

`chatsite hello` 不是公开 CLI；它属于脚手架示例残留，必须失败。

## 文档

- 文档首页：https://arch.gh.wzhecnu.cn/ChatSite/
- CLI 树：https://arch.gh.wzhecnu.cn/ChatSite/cli-tree/
- 英文文档：https://arch.gh.wzhecnu.cn/ChatSite/en/

## 开发说明

扩展命令前先阅读 `DEVELOP.md` 和 `AGENTS.md`，并保持 `--tree`、`--tree-brief`、README、MkDocs、测试与 changelog 同步。


## Todo 任务树工作台

安装 `"ChatSite[todo]>=0.1.5,<0.2.0"` 后执行 `chatsite todo serve`。SimpleMindMap 提供原生导图交互，Ant Design X 提供对话界面，ChatTodo 保持节点、版本、回执和撤销的领域职责；登录页与会话由 ChatLogin 共享核心提供，任务数据仍由 ChatTodo/ChatSite Todo 保存。前端随 Python 包分发，运行服务不需要 Node；维护界面源码时在 `frontend/todo/` 执行 `npm ci --ignore-scripts`、`npm test` 和 `npm run build`，并提交生成制品。

- [工作台使用与验收](docs/todo-workbench.md)
- [数据存储与模块接入](docs/todo-data-integration.md)：数据库、Node/Board/View、并发／幂等、Python/HTTP 与备份。

使用 `chatsite todo serve` 启动，`chatsite todo check` 验证配置和模型。配置由 ChatEnv 的 `chatsite-todo` provider 管理。模型支持 Responses／Chat Completions；使用 Plan 服务时应保留其 Plan 专属入口，不自动回退到按量计费。

## Overleaf / Hub Web

安装 `"ChatSite[overleaf]>=0.1.5,<0.2.0"` 后可运行 `chatsite-web`。Hub 与 `/overleaf` 是标准库 HTTP 服务，使用 ChatLogin UI-only 登录页、`/login/session` 和登录静态资源；浏览器写操作携带共享 CSRF。原 `chatsite.sqlite3` 继续保存 Settings、Overleaf 凭据/session、OpenAI key、对话和消息；登录 session 改存独立 `auth.sqlite3`，旧本地 session cookie 需要重新登录。

## ChatImg 文生图服务

安装 `"ChatSite[image-web]>=0.1.5,<0.2.0"` 后执行 `chatsite image serve`。根页面公开可用，访客可以继续按原 `/api/generate`、`/generated/<filename>`、`/api/images/<filename>` 路径生成、预览、下载和分享；登录是可选能力，登录后成功生成会写入当前账号自己的 SQLite 历史。历史接口只返回当前 Principal 的记录，访客不能枚举全局历史，也不会把旧匿名图片自动归到任意用户。

配置由 ChatEnv 的 `chatsite-image` provider 管理，运行数据默认在 `~/.chatarch/chatsite/image/`。模型凭据仍由 ChatImg/OpenAI profile 读取，ChatSite 不复制 API key。可配置 `CHATSITE_IMAGE_LEGACY_GENERATED_DIR` 作为旧匿名图片的只读 URL 兼容入口；迁移计划是先挂载只读旧目录、核对访问日志和文件生命周期，再由运维另行授权复制或归档，默认服务不会移动、删除或改属旧文件。
