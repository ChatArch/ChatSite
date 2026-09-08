# Todo 任务树工作台

Todo 是 ChatSite 的独立功能入口；ChatTodo 提供任务树领域 API，不重复实现 Web 主机。

## 能力

- 可平移、缩放的任务画布；节点可拖动、折叠、拆分和移动。
- 节点支持标题、状态、Markdown 正文及浮动的预览／编辑窗口。
- 右侧模型对话可隐藏；作用范围为当前分支或整棵任务树。
- 数据持久化到私有 SQLite；语义 revision 与视图状态分离。
- 变更批次原子应用，并提供请求幂等、冲突提示、变更记录和撤销。
- 模型输出必须通过 schema 与分支范围校验。删除、移动及完成/取消状态等重要操作需确认。
- 不在浏览器保存模型密钥；不执行模型生成的任意代码。

## 配置与运行

当前为开发构建，使用相互匹配的 ChatSite 与 ChatTodo 源码或 wheel，不能将历史占位包当成领域实现。

配置注册为 ChatEnv `chatsite-todo` provider，存储命名空间为 `ChatSiteTodo`。站点登录、模型地址/协议/型号及密钥只从这个配置边界读取。具名 profile 不会自动激活，也不会回退到其他账号的环境变量。

```bash
chatsite todo --help
chatsite todo check
chatenv test -t chatsite-todo -I
chatsite todo serve
```

`check`/`test` 会发送一次有界的真实模型请求，且不修改任务。服务默认监听回环地址，公网入口应由反向代理提供。

## 协议与数据

浏览器通过同源 session cookie 访问 API，写入还需要 CSRF token。模型连接在后端进行。Responses 使用无状态请求和按任务树隔离的本地历史，不把尚未回传 tool output 的响应 ID 当作下一次请求的有状态链。

节点字段为 `id / parent_id / title / status / body / order`。修改支持 `create / update / move / delete`；模型不能指定 owner 或访问其他任务树。HTTP 请求、节点数量、正文及模型响应都有边界限制。

运行目录由 `TodoSettings.data_dir` 统一描述，默认位于 ChatArch home 下的 `chatsite/todo`。目录私有，数据库文件权限为 0600。导出只包含任务数据，不包含登录信息或模型密钥。

## 验收

分别验证 Python 领域/API、Node 控制器、真实浏览器 DOM 和真实模型。页面打开或 `/health` 成功不代表功能已验收；需实际创建、编辑、保存、刷新、模型更新、危险操作确认和撤销，并检查错误路径与浏览器清理。
