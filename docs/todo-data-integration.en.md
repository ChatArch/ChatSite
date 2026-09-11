# Data Storage and Integration

A UI **Canvas is an API Board**. Each board independently stores its node forest, view and conversation. Empty Markdown bodies are valid: users can brainstorm using titles alone.

## Boundaries and storage

- **ChatTodo** owns validated domain operations, persistence, revisions, idempotency, history and undo.
- **ChatSite** owns browser/session/HTTP behavior, model calls and proposals.
- Integrating services own their project/event identities and mappings to board IDs. Do not add undeclared fields or write SQL directly. Automatic ChatAssign/ChatBoard synchronization, team membership management and a standalone Bearer-token API are not implemented.

The default data directory is `$CHATARCH_HOME/chatsite/todo/`, normally `~/.chatarch/chatsite/todo/`. `CHATSITE_TODO_DATA_DIR` overrides it; `TodoSettings.data_dir` is authoritative. Typed configuration belongs under the `ChatSiteTodo` ChatEnv namespace, not in the browser or source repository.

| Database | Tables and responsibility |
|---|---|
| `boards.sqlite3` | `boards` stores owner/title/revisions and JSON `nodes`/`view`; `changes` stores actual diffs; `undo_stack` stores node snapshots; `requests` stores request fingerprints and replay receipts |
| `auth.sqlite3` | ChatLogin session digests, principal, expiry and CSRF secret |
| `web.sqlite3` | `login_failures`, `conversations`, `messages`, `chat_requests`, `proposals`, `board_deletions`, and owner/board-scoped `presentations` |

Directories are private and database files use mode 0600. Web state uses SQLite WAL, so sidecar files may exist. Since 0.1.5, browser sessions are issued by the shared ChatLogin core and stored in `auth.sqlite3`; only SHA256 token digests cross the store boundary, never plaintext tokens. The principal owner remains the configured login email and is bound to the current configured email/password, so credential rotation rejects older sessions. Legacy Todo sessions in `web.sqlite3.sessions` are not migrated; users sign in once again and business data is not migrated or deleted. Conversation messages may contain private user content even though application API keys are not stored there.

Model request state advances through `pending → generated → done/failed`. Generation is saved before domain edits to avoid another model call during recovery. Model calls use stateless Responses with per-board local history. Message reads return the latest 200 messages; this is not a physical retention guarantee. Domain audit/request receipts use a bounded window (currently 1000); undo snapshots are separate. Idempotency is not a permanent external deduplication ledger.

Deletion is coordinated across two databases rather than a cross-database transaction. A known committed board deletion with failed conversation cleanup returns `board_deleted=true, cleanup_pending=true`; explicitly repeating the board deletion provides bounded cleanup recovery.

If imported layout persistence fails, the service compensates by removing the new board. `import_storage_error` means rollback completed; `import_rollback_pending` requires checking the rollback outcome, while `import_cleanup_pending` means only associated Web state needs cleanup. Pending errors identify the board for an explicit DELETE recovery, not another import. A concurrent semantic edit is never force-deleted to make rollback appear successful.

## Model

A Board contains `id, title, revision, nodes, view, view_revision, updated_at`. A Node contains:

```json
{"id":"goal","parent_id":null,"title":"Research directions","status":"pending","body":"","order":0}
```

Roots have null parents; multiple roots are supported. Use `(board_id,node_id)` as the full node locator. Status is `pending/in_progress/completed/cancelled`. Titles are non-empty and at most 200 characters; Markdown bodies are optional and at most 128 KiB. Limits: 2000 nodes, 64 levels, 50 operations per batch. Unknown fields, duplicate IDs, orphans and cycles are rejected.

View shape is `{pan:{x,y},zoom,positions:{node_id:{x,y}},collapsed:[node_id]}`. Coordinates are not parent relationships. Blank-canvas panning and pinch gestures change only the view, with zoom bounded to 0.2–2.5; dragging a node to reparent/reorder it submits semantic `move` operations. Invalid or stale node references are filtered.

`revision` tracks semantic edits; no-ops return `change=null` without incrementing it. `view_revision` is an independent compare-and-swap version. A stale view save returns 409 rather than overwriting another tab.

SimpleMindMap layout preferences belong to ChatSite's `presentations` table, not the ChatTodo domain schema. They have their own `revision` and do not advance either domain version. The default is `logicalStructure`; supported alternatives are `mindMap`, `organizationStructure`, `catalogOrganization`, `timeline`, and `fishbone`.

`request_id` binds the exact original input. Explicit recovery repeats the same ID and same body; do not mint a new ID after an ambiguous network failure. Only a verified conflict followed by deliberate reapplication should become a new attempt.

## Integration choices

Use `chattodo.board.BoardStore` inside trusted backend code. Derive `owner` from verified identity; the current Web service uses the authenticated login email. Core methods are `create`, `list`, `get`, `mutate`, `save_view(..., view_revision=...)`, `history`, `undo`, and `delete(..., confirm=True)`. `BoardError` exposes `code/message/status`.

```python
from pathlib import Path
from uuid import uuid4
from chattodo.board import BoardStore

store = BoardStore(Path("<private-data-dir>") / "boards.sqlite3")
owner = "user@example.invalid"  # use verified identity
board = store.create(owner, title="Project overview")
root = board["nodes"][0]["id"]
result = store.mutate(board["id"], owner, board["revision"], uuid4().hex, [
    {"op": "create", "node": {"id": uuid4().hex, "parent_id": root,
     "title": "One direction", "status": "pending", "body": "", "order": 0}}
])
current = store.get(board["id"], owner)
current["view"]["pan"]["x"] = 24
store.save_view(current["id"], owner, current["view"],
                view_revision=current["view_revision"])
```

Domain-only deletion does not clean ChatSite conversations. Prefer the coordinated HTTP delete path for a Web-managed board.

HTTP clients authenticate through the shared `/login` page or `/api/login`, retain its HttpOnly session cookie, obtain CSRF from login or `/api/session`, and include `X-CSRF-Token` on writes. `/api/login` remains compatible with `{email,password}` and also accepts `{username,password}`. Browser origins must be allowed and must not be duplicated.

| API | Contract |
|---|---|
| `GET/POST /api/boards` | List boards / create `{title}` |
| `GET/PATCH /api/boards/{id}` | Read / mutate `{revision,request_id,operations,confirm_destructive}` |
| `PATCH /api/boards/{id}/view` | `{view,view_revision}` |
| `GET/PATCH /api/boards/{id}/presentation` | `{layout,revision}`; stale saves return 409 |
| `POST /api/boards/{id}/undo` | `{revision,request_id}` |
| `GET /api/boards/{id}/history` | `{changes}` |
| `GET /api/boards/{id}/export` | Board JSON with optional Web `presentation` |
| `POST /api/import` | `{board}` imported as a new board, optionally restoring `presentation.layout`; legacy JSON remains supported |
| `DELETE /api/boards/{id}` | `{revision,confirm:true}` and committed/cleanup outcome |
| `GET /api/boards/{id}/messages` | Conversation ID and messages |
| `POST /api/boards/{id}/chat` | `{message,selected_node_id,revision,request_id}` |
| `POST /api/boards/{id}/apply` | `{proposal_id,revision,request_id,confirm_destructive:true}` |

Operations are `create/node`, `update/id/fields`, `move/id/parent_id/order` and `delete/id`. Delete includes descendants and requires confirmation. Model deletion/moves/completion/cancellation are proposals requiring user confirmation. The model cannot choose an owner, another board, or arbitrary executable tools.

Errors use `{"error":{"code":"...","message":"..."}}`. Distinguish 401 auth, 403 CSRF/origin, 409 version/request identity and 429 provider limits. A provider error is not a successful generated result.

## Backup and evolution

For a complete backup of tasks, sessions and conversations, include `boards.sqlite3`, `web.sqlite3`, `auth.sqlite3` and required private configuration. Use SQLite backup APIs for online files; copying only the main WAL database file is unsafe. For a cross-database consistent snapshot, pause writes through the supervisor, back up the databases, then resume.

Board JSON is an interchange format, not a complete backup of messages, receipts or undo history. Application credentials are excluded, but any sensitive content manually entered in node Markdown remains part of its content.

DDL currently lives in the Python modules; no dedicated migration CLI exists. Back up and test future structural upgrades. Deploy matched Web/domain builds and verify actual installed bytes: identical development version strings do not imply identical wheel contents.
