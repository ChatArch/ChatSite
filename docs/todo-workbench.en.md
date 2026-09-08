# Todo Workbench

The Todo feature belongs to ChatSite. ChatTodo supplies reusable task-forest operations and persistence, not another Web host.

## Features

- Left-hand canvas navigation: create, name and switch independent overview/project/idea canvases.
- Pan/zoom canvas with draggable, collapsible task cards; touch devices support two-finger zoom/pan without accidental node editing.
- [Storage and integration](todo-data-integration.md) documents both SQLite databases, schemas, revisions, idempotency, Python/HTTP contracts and backup boundaries.
- Right adds a child; top/bottom insert preceding/following siblings, preserving real relationships and order.
- Click a title to edit it in place; the separate detail button opens Markdown/PRD. Title-only brainstorming works without filling in any detail.
- Hideable model conversation panel scoped to the selected branch or the whole board.
- Private SQLite persistence, atomic batches, revisions, idempotency, history and undo.
- Structured model edits validated against schema and scope; important changes require confirmation.
- No model keys in the browser and no arbitrary execution of model-generated code.

## Configuration and execution

This is a development build. Install matching ChatSite and ChatTodo sources or wheels; the historical placeholder package does not implement the domain API.

The ChatEnv provider alias is `chatsite-todo`; its single storage namespace is `ChatSiteTodo`. Login credentials, model protocol/base/model/key and runtime paths belong to this configuration boundary. Explicit named profiles neither activate globally nor borrow another account's environment values.

```bash
chatsite todo --help
chatsite todo check
chatenv test -t chatsite-todo -I
chatsite todo serve
```

Checks send one bounded real no-edit model request. The service binds to loopback by default and is exposed through a reverse proxy.

## Data and protocol

Browser requests use same-origin session cookies and write-time CSRF validation. Model requests originate on the server. Stateless Responses calls use per-board local history; unfinished function-call response IDs are not reused as provider-side conversation chains.

Nodes contain `id`, `parent_id`, `title`, `status`, `body`, and `order`. Operations are `create`, `update`, `move`, and `delete`. Model output cannot select an owner or another board. Request sizes, node counts, content sizes and model responses are bounded.

`TodoSettings.data_dir` describes the runtime root, normally `chatsite/todo` under ChatArch home. Directories and SQLite files are private. Exports do not include login or model credentials.

Acceptance covers Python domain/API behavior, the JavaScript controller, real-browser DOM, and real model calls. A successful health response alone is not acceptance: exercise editing, reload persistence, proposals, confirmation, undo and failure paths.
