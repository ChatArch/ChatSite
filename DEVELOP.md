# Development Guide

## CLI Rules

- Current root-only commands use Click plus the ChatEnv provider entry point; add bounded `chatstyle` dependencies only when a real interactive command needs them.
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
- Keep `README.md`, `docs/`, and `CHANGELOG.md` in sync with user-facing changes.

## Automation

- Keep automation small and reviewable.
- Prefer commands that can run in CI without interactive prompts.
- Ensure generated defaults are safe for local development.
