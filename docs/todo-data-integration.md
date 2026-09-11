# 数据存储与模块接入

本文描述当前实现的契约。界面中的 **Canvas（画布）就是 API 中的 Board**：同一账号可以有多个画布，每个画布独立保存节点、视图与对话。画布可用于项目总览，也可只放若干标题做思维风暴；`body` 留空是正常状态。

## 组件边界

```text
其他业务模块 / 浏览器
        │
        ├─ 可信进程内调用 → chattodo.board.BoardStore
        │                    └─ boards.sqlite3
        │
        └─ 会话 + CSRF → ChatSite Todo HTTP API
                             ├─ BoardStore
                             ├─ auth.sqlite3
                             ├─ web.sqlite3
                             └─ 服务端模型适配器
```

- **ChatTodo**：树结构验证、原子语义操作、版本、幂等、历史、撤销与视图持久化。
- **ChatSite**：登录、浏览器、HTTP、模型上下文与提案、会话／消息状态。
- **接入方**：自己的项目 ID、事件、分派策略及 `project_id → board_id` 映射。不向节点塞入未定义字段，也不直接修改 SQLite。
- 尚未提供自动 ChatAssign/ChatBoard 同步、团队成员管理、单独的 Bearer API token 或后台同步任务；不能把下述 API 当成这些能力已经实现。

## 运行目录

默认数据根为 `$CHATARCH_HOME/chatsite/todo/`；未配置 ChatArch home 时通常为 `~/.chatarch/chatsite/todo/`。`CHATSITE_TODO_DATA_DIR` 可覆盖，最终以 `TodoSettings.data_dir` 为准。

```text
<ChatArch home>/
  envs/ChatSiteTodo/          # ChatEnv typed profiles，包含敏感配置
  chatsite/todo/
    boards.sqlite3          # 领域事实与回执
    auth.sqlite3            # ChatLogin 会话 digest 与 CSRF
    web.sqlite3             # 登录限流、对话、模型请求与提案
    web.sqlite3-wal          # 运行时可能存在的 SQLite WAL
    web.sqlite3-shm
```

部署环境可以把专用 venv、静态文档及备份也放在此运行根下，但它们不是 Board 数据模型。数据库目录使用私有权限，数据库文件为 `0600`。不要把 env、token、数据库放进源码仓库、前端静态资源或临时公开分享目录。

### `boards.sqlite3`

| 表 | 用途 |
|---|---|
| `boards` | `id / owner / title / revision / nodes / view / view_revision / updated_at`；`nodes` 与 `view` 是 JSON 文本 |
| `changes` | 实际节点 diff 的计数、摘要、actor、revision 与时间 |
| `undo_stack` | 用于撤销的节点快照；不是简单地对上一次结果来回切换 |
| `requests` | `board_id + request_id`、完整请求指纹及原始回执 |

每次调用独立连接并使用事务；写入校验失败不会留下部分节点变更。常规审计／请求回执有保留窗口（当前 1000）；不要把幂等回执当成永久去重账本。撤销快照与审计保留窗口分离。

### `auth.sqlite3`

Todo 0.1.5 起浏览器会话由 ChatLogin 共享核心签发并保存在独立数据库。存储层只接收 session token 的 SHA256 digest、Principal、到期时间与 CSRF secret，不保存原始 token；会话有容量上限、TTL，到期或退出后失效。Principal 的 owner 仍是配置的登录邮箱，并绑定当前配置的邮箱／密码；旋转凭据后旧会话不会被重新接受。旧版 `web.sqlite3.sessions` 会话不会迁移，用户需要重新登录一次，不会迁移或删除业务数据。

### `web.sqlite3`

| 表 | 用途 |
|---|---|
| `login_failures` | 登录限流窗口 |
| `conversations` | 按 `(owner, board_id)` 唯一的对话与非秘密响应元信息 |
| `messages` | 用户／助手内容，关联的 change／proposal；读取返回最近 200 条，不等于物理删除更早消息 |
| `chat_requests` | 请求指纹与 `pending / generated / done / failed` 状态、结果 |
| `proposals` | 高风险操作、基线版本、范围、应用状态及结果 |
| `board_deletions` | 跨两个数据库删除时的清理回执 |
| `presentations` | 按 `(owner, board_id)` 隔离的 Web 布局名称及独立 revision |

模型生成结果先写入请求状态，再应用领域变更，便于重放时避免再次调用模型。当前实现使用本地、按画布隔离的对话历史，向 Responses 发无状态请求；不会串用其他画布的响应链。

删除业务数据库中的内容不是一个跨库事务。领域画布已经删除但会话清理失败时，API 返回 `board_deleted=true, cleanup_pending=true`；再次提交同一画布的明确删除请求可完成有界恢复，不应将已删除误报为“删除失败”。

导入的布局写入若失败，会补偿撤回新画布。`import_storage_error` 表示已撤回；`import_rollback_pending` 表示撤回结果待核对，`import_cleanup_pending` 表示画布已撤回但关联状态还需清理。后两种错误会给出本次画布 ID，可通过明确的 DELETE 请求恢复，不要再次导入来掩盖未知结果。并发修改导致版本冲突时不会强制删除用户的新编辑。

## 数据模型

```json
{
  "id": "board-id",
  "title": "项目总览",
  "revision": 0,
  "nodes": [
    {"id": "goal", "parent_id": null, "title": "研究方向", "status": "pending", "body": "", "order": 0}
  ],
  "view": {
    "pan": {"x": 0, "y": 0}, "zoom": 1,
    "positions": {}, "collapsed": []
  },
  "view_revision": 0,
  "updated_at": "<UTC ISO timestamp>"
}
```

- `parent_id=null` 表示根节点，支持多个根的森林。节点标识在画布内唯一且稳定；定位时使用 `(board_id, node_id)`。
- `title` 必须非空，最多 200 字符；`body` 是可选的 Markdown，最大 128 KiB。
- `status`：`pending / in_progress / completed / cancelled`；`order` 为同级排序的非负整数。
- 最多 2000 节点、64 层，每批最多 50 个领域操作。非法字段、重复 ID、孤儿、环、自引用会被拒绝。
- 坐标不是父子关系。平移空白画布、鼠标滚轮、缩放按钮和双指手势只更新视图；拖拽节点重挂或排序会提交语义 `move` 操作。
- `zoom` 范围为 `0.2–2.5`；坐标必须是有界有限数值。`positions`、`collapsed` 中不再存在的节点引用会被过滤。

### 版本、回执与未知结果

- `revision` 只描述节点语义。真实无变化不增版本，`change=null`。
- `view_revision` 单独描述视图。HTTP 保存必须带读取时的 `view_revision`；过期版本返回 409，不能覆盖另一窗口的新视图。
- SimpleMindMap 的 Web 布局偏好独立保存在 `presentations`，不属于 ChatTodo 领域 schema，也不递增任务的 `revision` 或 `view_revision`。默认 `logicalStructure`；可选 `mindMap`、`organizationStructure`、`catalogOrganization`、`timeline`、`fishbone`。布局 API 的 `revision` 仅用于该偏好的并发保护。
- `request_id` 绑定**完整原始输入**。原请求重放返回回执；相同 ID 但不同请求体返回 409。
- 连接断开不代表写入失败。先读回或显式重试**相同 ID、相同原始请求体**；不能自动生成新 ID 再次调用模型。
- 只有确认是版本冲突、核对过最新状态后，才把重新应用作为新的请求。UI 保留未知写入的身份与编辑内容。

## Python 接入

适合具有可信身份与本地文件权限的后端进程；`owner` 必须来自接入方已经验证的身份，不能直接相信浏览器传入值。当前 Web 的 owner 是经过认证的站点登录邮箱。

```python
from pathlib import Path
from uuid import uuid4
from chattodo.board import BoardStore

store = BoardStore(Path("<private-data-dir>") / "boards.sqlite3")
owner = "user@example.invalid"  # 从已认证身份取得
board = store.create(owner, title="项目总览")
root = board["nodes"][0]["id"]
result = store.mutate(
    board["id"], owner, board["revision"], uuid4().hex,
    [{"op": "create", "node": {
        "id": uuid4().hex, "parent_id": root, "title": "一个方向",
        "status": "pending", "body": "", "order": 0,
    }}],
    actor="user",
)
current = store.get(board["id"], owner)
current["view"]["pan"]["x"] = 24
store.save_view(
    current["id"], owner, current["view"],
    view_revision=current["view_revision"],
)
```

其他方法：`list(owner)`、`history(board_id, owner)`、`undo(board_id, owner, revision, request_id)`、`delete(board_id, owner, revision, confirm=True)`。错误为 `BoardError`，提供 `code / message / status`。

纯 `BoardStore.delete` 不负责 ChatSite 会话清理。删除 Web 使用过的画布，优先通过 HTTP 删除流程，或显式采用 ChatSite 的清理协调逻辑。不要让两个模块分别删除一半后把结果说成完整成功。

## HTTP 接入

所有业务接口同源、会话认证。先通过共享 `/login` 页面或 `POST /api/login` 登录，复用返回的 HttpOnly session cookie；`/api/login` 保持 `{email,password}` 兼容，也接受 `{username,password}`。从登录结果或 `GET /api/session` 取得 CSRF token。写入发送 `X-CSRF-Token`，浏览器 Origin 必须被允许且不能重复。没有凭据的第三方不能直接调用。

| 方法与路径 | 输入／输出 |
|---|---|
| `GET /api/boards` | 当前 owner 的画布摘要列表 |
| `POST /api/boards` | `{title}` → `{board}`，自动有一个空正文主节点 |
| `GET /api/boards/{id}` | `{board}`；不存在或跨 owner 都返回 404 |
| `PATCH /api/boards/{id}` | `{revision, request_id, operations, confirm_destructive}` → `{board, change}` |
| `PATCH /api/boards/{id}/view` | `{view, view_revision}` → `{view, view_revision}` |
| `GET /api/boards/{id}/presentation` | `{layout, revision}` |
| `PATCH /api/boards/{id}/presentation` | `{layout, revision}` → 当前布局偏好；版本过期返回 409 |
| `POST /api/boards/{id}/undo` | `{revision, request_id}` → `{board, change}` |
| `GET /api/boards/{id}/history` | `{changes}` |
| `GET /api/boards/{id}/export` | 画布 JSON，包含可选 Web `presentation`，不含应用登录／模型配置 |
| `POST /api/import` | `{board}` → 新画布；可恢复 `presentation.layout`，不覆盖已有画布；旧 JSON 仍可导入 |
| `DELETE /api/boards/{id}` | `{revision, confirm:true}` → 删除／清理状态 |
| `GET /api/boards/{id}/messages` | 对话 ID 与消息列表 |
| `POST /api/boards/{id}/chat` | `{message, selected_node_id, revision, request_id}` → 助手消息、画布、change／proposal |
| `POST /api/boards/{id}/apply` | `{proposal_id, revision, request_id, confirm_destructive:true}` → 已确认结果 |

错误统一为 `{"error":{"code":"...","message":"..."}}`。常见：401 未登录，403 CSRF／Origin，409 版本／请求身份冲突，429 模型忙或上游限流。不能用 HTTP 200 的 HTML 登录页冒充 JSON 成功结果。

领域操作形状：

```json
[
  {"op":"create","node":{"id":"new-id","parent_id":"goal","title":"新想法","body":"","status":"pending","order":0}},
  {"op":"update","id":"new-id","fields":{"title":"新的标题"}},
  {"op":"move","id":"new-id","parent_id":null,"order":1},
  {"op":"delete","id":"new-id"}
]
```

删除会包含后代并要求确认。模型的删除、移动、完成／取消等重要操作先形成提案；模型不能决定 owner、切换别的画布或执行任意代码。

## 备份与演进

- 需要保留完整任务、会话与对话时，备份 `boards.sqlite3`、`web.sqlite3`、`auth.sqlite3` 及必要的私有 ChatEnv 配置；不要把备份公开。
- 对在线 SQLite 使用 SQLite backup API，不能只复制主文件而忽略 WAL。要获得跨库一致的完整快照，先通过 supervisor 暂停本服务写入，完成两个备份再恢复。
- JSON 导出用于交换一个画布的节点与视图，不包含完整会话、幂等账本或所有撤销状态。正文按原样导出：用户自行写入的敏感内容不会自动消失。
- 当前 DDL 随 Python 模块维护，没有独立 schema-migration CLI；结构升级应先备份并测试迁移。
- Web 与领域包必须成对更新并核对真实安装代码；相同开发版本号并不能证明 wheel 内容相同。
- 接入方优先复用上述 Python API 或 HTTP；后续增加事件同步、任务分派、常规树视图时，不应重建一套相互分离的节点事实。
