# Todo Workbench

The Todo feature belongs to ChatSite. ChatTodo supplies reusable task-forest operations and persistence, not another Web host.

## Features

- Left-hand canvas navigation: create, name and switch independent overview/project/idea canvases.
- Native SimpleMindMap editing: select, double-click/F2 for titles, Tab for children, Enter for siblings, drag/reparent, multiselect, collapse and layout selection. Touch devices support two-finger zoom and pan.
- [Storage and integration](todo-data-integration.md) documents both SQLite databases, schemas, revisions, idempotency, Python/HTTP contracts and backup boundaries.
- Nodes are plain text. Optional Markdown/PRD belongs in a separate detail panel; rich-text or arbitrary HTML map nodes are not enabled.
- Ant Design X conversation panel with user/assistant messages, Markdown/code, copy and change receipts; scope it to a selected branch or the whole board and collapse it on narrow screens.
- Single-root canvases open directly. Existing forests expose an explicit root selector: editing one branch preserves all other roots. Empty canvases can add a new center node.
- Private SQLite persistence, atomic batches, revisions, idempotency, history and undo.
- Structured model edits validated against schema and scope; important changes require confirmation.
- No model keys in the browser and no arbitrary execution of model-generated code.

## Configuration and execution

Install `"ChatSite[todo]>=0.1.5,<0.2.0"` with pip. The extra resolves the compatible ChatTodo domain dependency (`>=0.1.0,<0.2.0`) and ChatLogin Web login core (`>=0.1.2,<0.2.0`). The Python package includes the frontend build; deployment requires neither Node nor a runtime CDN.

Models may use Responses or Chat Completions. Ark Agent Plan supports `doubao-seed-evolving` through Responses; retain the provider's Plan endpoint without automatic pay-as-you-go fallback. Run configuration checks in the same environment that has Todo installed so ChatEnv can discover its provider.

The ChatEnv provider alias is `chatsite-todo`; its single storage namespace is `ChatSiteTodo`. Login credentials, model protocol/base/model/key and runtime paths belong to this configuration boundary. Explicit named profiles neither activate globally nor borrow another account's environment values.

```bash
chatsite todo --help
chatsite todo check
chatenv test -t chatsite-todo -I
chatsite todo serve
```

Checks send one bounded real no-edit model request. The service binds to loopback by default and is exposed through a reverse proxy.

## Data and protocol

Browser requests use same-origin session cookies and write-time CSRF validation. `/login` uses ChatLogin's shared login page assets; `/api/login` remains compatible with `{email,password}` and also accepts the shared form's `{username,password}`. Model requests originate on the server. Stateless Responses calls use per-board local history; unfinished function-call response IDs are not reused as provider-side conversation chains.

Before submitting, the shared login page reads public `GET /login/session`: anonymous, invalid/expired or logged-out sessions receive `200 {"authenticated":false}`. Valid sessions expose only `authenticated`, `email` and `csrf_token`, never passwords, model keys or the raw session token; responses are not cached. Non-authentication failures such as storage errors remain errors, not anonymous responses. The workbench recovery endpoint `GET /api/session` still returns `401` when unauthenticated. Login and bootstrap URLs honor `root_path`; a missing or unsafe `next` defaults to the current mount root in both the page and login response (`/` at the site root, for example `/mounted/` when mounted). Explicit safe same-site `next` paths are preserved.

Ordinary conversation may return natural language, Markdown or JSON examples without modifying the board. Edits require a real `todo_update` tool call with validated arguments; malformed, unknown or multiple tool calls never become executable text. Definite model-generation failures allow a new user request, while missing write receipts retain the original request identity for retry.

Nodes contain `id`, `parent_id`, `title`, `status`, `body`, and `order`. Operations are `create`, `update`, `move`, and `delete`. Model output cannot select an owner or another board. Request sizes, node counts, content sizes and model responses are bounded.

`TodoSettings.data_dir` describes the runtime root, normally `chatsite/todo` under ChatArch home. Directories and SQLite files are private. ChatLogin sessions live in a separate `auth.sqlite3`; tasks, conversations, proposals and view state stay in the existing business databases. Upgrading to 0.1.5 does not migrate old Todo local sessions, so users sign in once again; business data is not migrated or deleted. Exports do not include login or model credentials.

## Development and acceptance

Undo uses server history for both manual edits and applied model changes. Redo uses revision-guarded snapshots from the current page session; other semantic edits or a reload invalidate them. The model endpoint returns completed results, not fake streaming or a nonfunctional cancel action. Native text edits are committed before sending, navigation or logout; ambiguous writes retain the original request for explicit retry.

Frontend source lives under `frontend/todo/`. Run `npm ci --ignore-scripts`, `npm test`, and `npm run build`; commit the generated `src/chatsite/todo_static/` output with source changes. CI verifies rebuild consistency. Map/chat dependencies are locked and their notices ship with the static assets.

Acceptance covers Python domain/API behavior, the JavaScript controller, real-browser DOM, and real model calls. A successful health response alone is not acceptance: exercise editing, reload persistence, proposals, confirmation, undo and failure paths.
