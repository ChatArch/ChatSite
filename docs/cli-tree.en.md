# CLI Tree

This tree follows the registered Click command names and signatures; the annotations below are translated into English. The full tree includes signatures; the brief tree omits them.

```text
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
├── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
└── todo  # Task-tree workbench.
    ├── check [--profile PROFILE] [--home HOME]  # Check configuration and send one no-edit model request.
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # Start the task-tree Web service.
```

`chatsite todo serve` starts the task workbench. `chatsite todo check` sends one bounded no-edit model request using the typed ChatEnv profile.

`--tree-brief` preserves this hierarchy and omits the bracketed parameter signatures. The removed scaffold hello command remains unsupported.
