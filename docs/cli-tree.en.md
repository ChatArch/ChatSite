# CLI Tree

`chatsite --tree` is generated from the real registered Click command surface. `ChatSite` currently exposes root-level package information entries only and no business subcommands; a template `hello` command is not part of the public interface.

## Top-level command

```text
chatsite  # ChatSite package scaffold for site workflows
├── --help  # show command help
├── --version  # show the installed package version
└── --tree  # show this CLI tree
```

## Status Contract

- `chatsite --help` must expose `--tree`.
- `chatsite --tree` must exit 0 and list only real registered commands/options.
- `chatsite hello` must fail; `hello` is not a business command.
- Future site capabilities must add reusable Python APIs first, then CLI commands, and then update this page.
