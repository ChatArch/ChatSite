# ChatSite

`ChatSite` 是 ChatArch 站点工作流方向的 Python CLI 包壳。当前公开 CLI 只提供包信息与真实命令树；后续新增站点能力时，应先落到可复用 Python API，再扩展 CLI、文档和测试。

<div class="grid cards" markdown>

-   :material-console-line: **CLI 树**

    ---

    查看当前真实命令面：[`chatsite --tree` / `chatsite --tree-brief`](cli-tree.md)。

-   :material-web: **站点边界**

    ---

    当前版本是轻量入口，不部署或修改真实站点。

-   :material-shield-check: **验证契约**

    ---

    `--tree`、`--tree-brief`、README、MkDocs 和测试必须同步更新。

</div>

## 快速开始

```bash
pip install chatsite
chatsite --version
chatsite --tree
chatsite --tree-brief
```

## 开发验证

```bash
pip install -e ".[dev,docs]"
python -m pytest -q
mkdocs build --strict
python -m build
```
