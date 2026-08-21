# Development Guide

## CLI Rules

- The `chatsite` console script uses Click plus `chatstyle>=0.2.0,<0.3.0`; keep `--version`, `--tree`, and `--tree-brief` on the explicit root command.
- Use ChatStyle `add_tree_option()` and the registered command renderer instead of adding a package-local tree implementation.
- Keep the typed ChatEnv provider on `chatenv>=0.2.10,<0.3.0` and use ChatEnv profile/storage paths for configuration state.
- Prefer reusable Python APIs before CLI wiring for new site capabilities.
- Missing required args should auto-enter interactive mode only when recoverable and explicitly designed.
- `-i` forces interactive mode; `-I` disables prompting and must fail fast.
- Prompt defaults must match actual execution defaults.
- Sensitive values must stay masked in prompts and summaries.
- Prefer lazy imports in CLI wiring and keep implementation imports local when possible.

## Docs and Tests

- Use doc-first CLI testing.
- Put real CLI coverage under `tests/cli-tests/`.
- Put mock/fake CLI coverage under `tests/mock-cli-tests/`.
- Keep `--tree`, `--tree-brief`, `README.md`, `docs/`, and `CHANGELOG.md` in sync with user-facing changes.

## Automation

- Keep automation small and reviewable.
- Prefer commands that can run in CI without interactive prompts.
- Ensure generated defaults are safe for local development.
