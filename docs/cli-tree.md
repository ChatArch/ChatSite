# CLI 树

`chatsite --tree` 与 `chatsite --tree-brief` 由 ChatStyle 从真实注册的 Click command surface 生成。当前 `ChatSite` 只有根级包信息入口，没有业务子命令；模板 `hello` 命令不属于公开接口。

## 顶层命令

```text
chatsite
├── --help  # Show this message and exit.
├── --version  # Show the version and exit.
├── --tree  # Print the registered CLI tree and exit.
└── --tree-brief  # Print the registered CLI tree without parameter signatures and exit.
```

当前没有带参数的子命令，因此完整树与 brief 树相同。以后增加命令参数时，`--tree` 显示签名，`--tree-brief` 省略签名。

## 状态契约

- `chatsite --help` 必须暴露 `--tree` 与 `--tree-brief`。
- `chatsite --tree` 必须 exit 0，并只列出真实注册的命令/选项。
- `chatsite --tree-brief` 必须 exit 0，并显示同一命令面且省略命令参数签名。
- `chatsite hello` 必须失败；`hello` 不是业务命令。
- 新增站点能力时，先增加可复用 Python API，再新增 CLI command，并同步本页。
