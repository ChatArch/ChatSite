# CLI Tree

This tree follows the registered Click command names and signatures; the annotations below are translated into English. The full tree includes signatures; the brief tree omits them.

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
├── image  # ChatImg image generation service.
│   ├── check [--profile PROFILE] [--home HOME]  # Validate Image configuration without generating an image.
│   └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # Start the ChatImg web service.
└── todo  # Task-tree workbench.
    ├── check [--profile PROFILE] [--home HOME]  # Validate configuration and model with a small read-only request.
    └── serve [--host HOST] [--port PORT] [--profile PROFILE] [--home HOME]  # Start the task-tree web service.
```

`chatsite todo serve` starts the task workbench. `chatsite todo check` sends one bounded no-edit model request using the typed ChatEnv profile.
`chatsite image serve` starts the public image page. `chatsite image check` validates Image configuration without generating an image.

`--tree-brief` preserves this hierarchy and omits the bracketed parameter signatures. The removed scaffold hello command remains unsupported.
