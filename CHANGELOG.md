# Changelog

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
