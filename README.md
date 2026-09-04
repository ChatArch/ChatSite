<div align="center">
    <a href="https://pypi.python.org/pypi/chatsite">
        <img src="https://img.shields.io/pypi/v/chatsite.svg" alt="PyPI version" />
    </a>
    <a href="https://github.com/ChatArch/ChatSite/actions/workflows/ci.yml">
        <img src="https://github.com/ChatArch/ChatSite/actions/workflows/ci.yml/badge.svg" alt="Tests" />
    </a>
    <a href="https://arch.gh.wzhecnu.cn/ChatSite/">
        <img src="https://img.shields.io/badge/docs-mkdocs-blue.svg" alt="Documentation" />
    </a>
</div>

<div align="center">

[英文版](README.en.md) | 简体中文
</div>

# ChatSite

`ChatSite` 是 ChatArch / Chat 系列的 Web 与 service 入口。它从模板包壳开始演进：CLI 仍保持真实 root-only 包信息入口，Web feature 则在这里集成各 Chat 工具能力；例如 Overleaf 编辑页面由 ChatSite serve，并调用 ChatOL 作为 Overleaf 工具模块。后续新增站点能力时，必须同步 Python API、服务入口、文档和测试。

## 快速开始

```bash
pip install chatsite
chatsite --version
chatsite --tree
chatsite --tree-brief
```

开发环境：

```bash
pip install -e ".[dev,docs]"
python -m pytest -q
mkdocs build --strict
python -m build
```

## CLI 树

```text
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
└── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
```

当前公开接口只有 root options，因此完整树与 brief 树相同；新增带参数的真实命令后，`--tree` 保留签名，`--tree-brief` 省略签名。

`chatsite hello` 不是公开 CLI；它属于脚手架示例残留，必须失败。

## 文档

- 文档首页：https://arch.gh.wzhecnu.cn/ChatSite/
- CLI 树：https://arch.gh.wzhecnu.cn/ChatSite/cli-tree/
- 英文文档：https://arch.gh.wzhecnu.cn/ChatSite/en/

## 开发说明

扩展命令前先阅读 `DEVELOP.md` 和 `AGENTS.md`，并保持 `--tree`、`--tree-brief`、README、MkDocs、测试与 changelog 同步。
