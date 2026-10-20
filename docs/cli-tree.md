# CLI 树

以下树来自真实注册的 Click 命令。完整树包含参数签名，brief 树只显示命令和说明。

```text
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
├── hosting [--profile PROFILE] [--home HOME]  # Upload dev sites, publish reviewed versions, and manage site access.
│   ├── bootstrap [--username USERNAME] [--password-env PASSWORD-ENV]  # Server operator only: create the first hosting owner in an empty account directory.
│   ├── create <SITE> [--title TITLE] [--owner OWNER] [--alias ALIAS] [--trusted]  # Administrator: register a private site, with isolated scripts by default.
│   ├── grant <SITE> [--user-id USER-ID] [--role ROLE]  # Administrator: grant or revoke access to one private site.
│   ├── login [--url URL] [--username USERNAME] [--password-env PASSWORD-ENV]  # Sign in with an administrator-provisioned account; save a private session.
│   ├── logout  # Revoke this CLI session on the server.
│   ├── publish <SITE> [--release RELEASE] [--yes]  # Publish an explicitly selected version to production.
│   ├── rollback <SITE> [--release RELEASE] [--yes]  # Restore a previously published production version; dev is unchanged.
│   ├── sites  # List sites this account may read.
│   ├── upload <SITE> <DIRECTORY>  # Upload a static directory to dev; production is unchanged.
│   ├── users  # Administrator account provisioning; public registration stays closed.
│   │   ├── create <USERNAME> [--password-env PASSWORD-ENV] [--role ROLE]  # Create an account; the password is never printed or stored in the repository.
│   │   ├── disable <USER-ID>  # Disable a user and revoke all of their hosting sessions.
│   │   └── list  # List safe account metadata.
│   ├── versions <SITE>  # List immutable versions for a site.
│   └── whoami  # Show the current account without session or CSRF values.
├── image  # ChatImg 文生图服务。
│   ├── check [--profile PROFILE] [--home HOME]  # 验证 Image 配置，不发起图片生成。
│   └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动 ChatImg Web 服务。
└── todo  # 任务树工作台。
    ├── check [--profile PROFILE] [--home HOME]  # 验证配置及模型，会发送一次不修改任务的小请求。
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # 启动任务树 Web 服务。
```

`chatsite todo serve` 启动任务树工作台；`chatsite todo check` 读取 ChatEnv 配置并发送一次有界、无任务修改的模型检查。
`chatsite image serve` 启动公开文生图页面；`chatsite image check` 只验证 Image 配置，不发起图片生成。

`--tree-brief` 显示同样的命令层级，但省略方括号中的参数签名。模板 hello 命令仍不是公开接口。
