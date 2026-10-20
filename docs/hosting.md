# 静态网站托管

ChatSite 提供私有静态站点、明确的站点授权，以及 CLI 驱动的开发→正式发布流程。公共注册关闭；管理员先开通账号、登记站点，再授予阅读或发布权限。Coolify 管理容器和应用基础设施，ChatSite 管理这套网页、权限与版本；使用此功能不要求安装 Coolify 或配置 CI。

## 本地开发与发布

```sh
python -m pip install ChatSite
chatsite hosting login --url https://chat.example.com --username YOUR_ACCOUNT
chatsite hosting sites
chatsite hosting upload my-notes ./dist
```

目录根必须有 `index.html`；全部资源应适配子路径。上传返回不可变版本 ID 和开发链接 `/sites/my-notes/dev/`。开发版更新不会改变正式版。

检查开发页面后，明确选择刚才的版本：

```sh
chatsite hosting publish my-notes --release VERSION
chatsite hosting versions my-notes
chatsite hosting rollback my-notes --release PREVIOUS_VERSION
```

正式链接为 `/sites/my-notes/prod/`。管理员可以给站点配置 `/my-notes/` 等短路径，它始终读取同一个正式版本；发布与回退同时影响两种地址。回退仅接受以前发布过的版本，不改变开发版。交互终端会确认发布；脚本可在检查版本后显式加 `--yes`。这是 **CLI** 工作流，CI 不是必需条件。

多个账号/服务器可通过 `chatsite hosting --profile NAME ...` 隔离登录会话；`--home` 选择 ChatArch home。会话保存在 ChatEnv TokenStore 中，密码不会保存。非交互登录使用 `--password-env ENV_KEY`，参数是环境变量名，不是密码值。`logout` 撤销当前服务器会话；有效期为一天，过期后重新登录。

## 管理员开通

管理页 `/hosting/` 可以开通账号、登记站点、授予/撤销权限、停用用户、查看开发和正式链接及选择版本发布。也可使用 CLI：

```sh
chatsite hosting users create alice --password-env INITIAL_PASSWORD
chatsite hosting users list
chatsite hosting create my-notes --title "我的笔记" --owner USER_ID --alias my-notes
chatsite hosting grant my-notes --user-id USER_ID --role publisher
chatsite hosting grant my-notes --user-id USER_ID --role viewer
chatsite hosting grant my-notes --user-id USER_ID --role none
chatsite hosting users disable USER_ID
```

全局 owner / admin 可以管理站点；只有 owner 可以开通 admin。站点 viewer 可读开发和正式版；publisher 可读、上传、发布与回退。账号本身不自动获得任何站点权限。停用用户会撤销其所有托管会话，撤销站点授权会立即阻止后续读取和发布。

## 服务端启用

安装 `ChatSite[overleaf,hosting]`。复用已有 Hub 的 `chatsite-web` 进程，设置 `CHATSITE_HOSTING_ENABLED=true`；托管业务数据默认位于 Hub data-dir 的 `hosting/`，可用 `CHATSITE_HOSTING_DATA_DIR` 覆盖。身份与会话采用 ChatLogin managed users，位于 ChatArch home 下的 `chatlogin/instances/chatsite-hosting/`。没有公开 bootstrap API；服务器操作者只在空账号目录执行一次：

```sh
chatsite hosting bootstrap --username owner@example.test --password-env EXISTING_OWNER_PASSWORD
```

使用原 Hub 的 owner 账号和密码开通托管 owner 后，原 Hub 会话也可打开管理页和有权限的站点。原 `/api/login` 仍只接受原 Hub owner；新增账号登录 `/hosting/login`，不会获得旧 Hub / Overleaf 权限。新托管 cookie 为 `chatsite_hosting_session`；CLI 使用显式 Bearer 会话。Cookie 写入同时检查 Origin 和 CSRF。

## 隔离与边界

每份 HTML、CSS、JavaScript 和数据文件都检查当前账号及站点授权。版本目录不可变，上传只更新数据库中的开发版指针，发布事务只切换正式版指针；旧版本保留供回退。归档限制为压缩32 MiB、展开64 MiB、2000项；拒绝越界、符号链接、`.env`、`.git`、重复条目和加密归档。每站最多200个版本，达到上限需管理员安排归档，系统不会自动删除旧版本。

默认站点响应使用 CSP sandbox，使页面脚本不能获得管理站点的同源权限。浏览器存储及基于同源 fetch 的扩展在该模式下受限。管理员只可对完全可信的代码和发布者选择 `--trusted`，以启用本地存储、同源留言等扩展；这些脚本与管理入口共享权限边界，授予该站发布权限就意味着信任其代码。所有站点禁止注册 Service Worker。[CSP sandbox 的浏览器语义](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox)。

通用托管只负责静态文件。留言等后端数据应放在独立持久目录，通过已认证的服务端路由接入；不得把它们打包进静态 release。集成时使用 `HostingHandler._hosting_auth(write=...)` 取得当前主体，再调用 `handler.hosting.store.check(actor, site_id)` 检查该站权限；留言管理还需检查角色，不得把任意登录用户当成管理员。

## Python 与 API

`chatsite.hosting_client.HostingClient` 提供 `login`、`upload`、`publish` 与 `request`；`chatsite.hosting.HostingStore` 提供站点、授权、版本及读取的 Python API。`/api/hosting/session` 返回当前主体及 CSRF，匿名为401；`/api/hosting/register` 固定403。站点与版本接口在 `/api/hosting/sites` 下。客户端不跟随重定向，避免将 Bearer 会话转发到其他域名。
