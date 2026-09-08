# CLI Tree

This tree comes from the registered Click commands. The full tree includes signatures; the brief tree omits them.

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

`chatsite todo serve` starts the task workbench. `chatsite todo check` sends one bounded no-edit model request using the typed ChatEnv profile.

`--tree-brief` preserves this hierarchy and omits the bracketed parameter signatures. The removed scaffold hello command remains unsupported.
