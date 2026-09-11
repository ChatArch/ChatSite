# Changelog

## 2026-09-11 - 0.1.5

### 新增

- 新增 `chatsite image serve/check` 与 `chatsite-image` 服务入口：访客继续使用 ChatImg 文生图，登录用户获得自己的持久生成历史。
- Image 服务复用 ChatLogin 会话、共享登录页、CSRF 和同源保护；历史按 Principal 隔离，旧匿名文件只读兼容且不会自动归属到用户。

### 改进

- Todo 登录页与会话接入 ChatLogin 共享核心，保留 `/api/login` 的 `email/password` JSON 响应兼容，并支持共享登录页的 `username` 字段。
- Todo 会话改存独立 `auth.sqlite3`，只保存 token digest、Principal、到期时间和 CSRF secret；旧版本地会话需要重新登录一次，任务、对话、提案和视图数据不迁移也不删除。
- 保留同源、CSRF、Secure/HttpOnly/SameSite cookie 与 8 次/300 秒登录限流，并增加持久会话、凭据轮换、共享登录资源和真实 TCP auth 回归覆盖。
- Hub/Overleaf 标准库 HTTP 服务接入 ChatLogin 共享 `/login`、`/login/session`、登录资源和 CSRF，会话存入独立 `auth.sqlite3`；原 `chatsite.sqlite3` 的 Settings、Overleaf/OpenAI secret、对话和消息继续作为业务数据权威。
- Hub/Overleaf extra 使用 `ChatLogin[ui]>=0.1.3`，共享登录资源通过 package-root 读取，避免标准库 HTTP Hub 额外拉入 FastAPI/Starlette。

## 2026-09-09 - 0.1.4

### 改进

- Todo 改用 SimpleMindMap 原生导图与 Ant Design X 聊天组件，支持原生键盘、拖拽、布局和移动端交互。
- 保留 ChatTodo 数据契约与账号：多根森林显式切换分支，不转换节点身份或丢弃其他根。
- 增加独立、带版本冲突保护的 Web 布局偏好；JSON 导入导出携带布局，不改变任务语义版本。
- 节点编辑与模型修改共用服务端撤销；重做使用当前会话中受版本保护的快照。
- 普通模型对话直接返回自然语言或 Markdown；只有结构化 `todo_update` 才能修改任务。
- 前端源码、锁定依赖与生成制品纳入包和 CI；更新中英文交互、存储与开发说明。
- 文档依赖采用兼容 Material 9 系列的上限，避免无必要的环境降级。

## 2026-09-09 - 0.1.3

### 新增

- 独立 Todo 工作台：多画布导航、标题优先思维导图、三方向新增、原地编辑与可选 Markdown 详情。
- 手机双指缩放／平移、独立视图版本、草稿恢复、原请求重试及画布切换保护。
- ChatTodo 领域包集成、同源登录和 CSRF、任务与对话持久化、原子修改、回执、确认和撤销。
- 兼容 Responses 与 Chat Completions 的服务端模型适配，包括 Ark Plan 的 Evolving 模型；结构化提案及分支范围校验。
- 中英文使用、存储与模块接入文档，Todo Python／JavaScript 回归加入发布 CI。
- 登录保护的 ChatSite 功能首页、Overleaf 编辑器与 ChatOL 工具集成。

## 2026-08-22 - 0.1.2

### Changed

- Replaced the package-local CLI tree renderer with ChatStyle's registered Click renderer and added `chatsite --tree-brief`.
- Aligned runtime dependencies with `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.10,<0.3.0`, with typed ChatEnv provider and storage-path coverage.
- Expanded CI across Python 3.10-3.12 with installed CLI, wheel, and Twine checks.

## 2026-08-12 - 0.1.1

### Changed

- Added generated root-only `chatsite --tree` from the Click command surface.
- Added bilingual MkDocs docs, CLI tree pages, Preview Docs, Deploy Docs, CI docs gate, and workflow/docs contract tests.
- Removed unused direct ChatStyle runtime dependency while preserving the ChatEnv provider entry point.

## 2026-06-29 - 0.1.0

### Added

- Initial chatsite package scaffold with `chatsite` CLI.
- ChatEnv provider entry point for `chatsite` configuration discovery.
- CI and tag-driven PyPI Trusted Publisher workflow scaffold.
