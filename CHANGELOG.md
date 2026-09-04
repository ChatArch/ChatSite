# Changelog

## Unreleased

### Added

- Added ChatSite's first feature service: `chatsite-overleaf-web`, a login-protected Overleaf editing page that calls ChatOL as a tool module and supports project/file browsing, OT-based doc saves, compile previews, Settings, and an OpenAI Responses API chat loop.

## 2026-08-22 - 0.1.2

### Changed

- Replaced the package-local CLI tree renderer with ChatStyle's registered Click renderer and added `chatsite --tree-brief`.
- Aligned runtime dependencies with `chatstyle>=0.2.0,<0.3.0` and `chatenv>=0.2.10,<0.3.0`, with typed ChatEnv provider and storage-path coverage.
- Expanded CI across Python 3.10-3.12 with installed CLI, wheel, and Twine checks.

## 2026-08-12 - 0.1.1

### Changed

- Added generated root-only `chatsite --tree` from the Click command surface.
- Added bilingual MkDocs docs, CLI tree pages, Preview Docs, Deploy Docs, CI docs gate, and workflow/docs contract tests.
- Removed unused direct ChatStyle runtime dependency while preserving the ChatEnv provider entry point.

## 2026-06-29 - 0.1.0

### Added

- Initial chatsite package scaffold with `chatsite` CLI.
- ChatEnv provider entry point for `chatsite` configuration discovery.
- CI and tag-driven PyPI Trusted Publisher workflow scaffold.
