# ChatSite

`ChatSite` is the ChatArch Python CLI package shell for site-oriented workflows. The public CLI currently exposes package metadata and the real command tree only; future site capabilities should start with reusable Python APIs before extending CLI commands, docs, and tests.

<div class="grid cards" markdown>

-   :material-console-line: **CLI Tree**

    ---

    Inspect the current real command surface: [`chatsite --tree`](cli-tree.md).

-   :material-web: **Site Boundary**

    ---

    The current version is a lightweight entrypoint and does not deploy or mutate real sites.

-   :material-shield-check: **Verification Contract**

    ---

    `--tree`, README, MkDocs, and tests must stay synchronized.

</div>

## Quick Start

```bash
pip install chatsite
chatsite --version
chatsite --tree
```

## Development Verification

```bash
pip install -e ".[dev,docs]"
python -m pytest -q
mkdocs build --strict
python -m build
```
