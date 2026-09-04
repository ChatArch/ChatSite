# ChatSite Web and Overleaf Feature

ChatSite is the web/service entry point for the Chat series. The Overleaf editor
feature lives here and calls ChatOL as a tool module; ChatOL does not serve the
web application.

## What It Provides

- A browser login page for the ChatSite hub.
- An `/overleaf` feature workspace for Overleaf editing.
- Server-side Settings for the Overleaf endpoint, Overleaf credentials/session,
  OpenAI model, and OpenAI API key.
- Project and file browsing against the configured Overleaf instance.
- Single-file reading through Overleaf's internal doc download route.
- Existing doc saves through Overleaf's real-time OT update channel.
- New root-level text file creation through ChatOL upload.
- Project compile with authenticated PDF/log artifact preview.
- Conversation history with one OpenAI Responses API tool named `overleaf`.
- Per-conversation OpenAI Responses API state: each conversation stores its own
  `previous_response_id` chain so model/tool context is isolated across chats.

## Runtime Boundary

ChatSite owns:

- HTTP serving and static assets
- configurable login/session management
- user-facing Settings
- conversation state
- service deployment and nginx/public entry

ChatOL owns:

- Overleaf login/session bootstrap using Overleaf tool credentials from Settings
  or the private Overleaf deployment env
- project/file workflow primitives
- compile/download APIs
- Overleaf-specific data models and errors

## Environment

Required for login:

- `CHATSITE_WEB_ADMIN_PASSWORD` or `CHATSITE_WEB_ADMIN_PASSWORD_FILE`

Recommended for deployment:

- `CHATSITE_WEB_ADMIN_EMAIL`, default `admin@example.test`
- `CHATSITE_WEB_HOST`, default `127.0.0.1`
- `CHATSITE_WEB_PORT`, default `18082`
- `CHATSITE_WEB_DATA_DIR`, default `~/.chatarch/chatsite`
- `CHATSITE_OVERLEAF_DEFAULT_URL`, default `http://127.0.0.1:8090`
- `CHATSITE_OVERLEAF_ENV_FILE`, points at an existing private Overleaf `.env`
- `OPENAI_API_KEY` or `CHATSITE_OPENAI_API_KEY`
- `OPENAI_BASE_URL`, default `https://api.openai.com/v1`
- `OPENAI_MODEL` or `CHATSITE_WEB_OPENAI_MODEL`, default `gpt-5.5`

Do not commit passwords, session cookies, API keys, or deployment `.env` files.

## Local Run

```bash
PYTHONPATH=/path/to/ChatSite/src:/path/to/ChatOL/src \
CHATSITE_WEB_ADMIN_PASSWORD_FILE=/path/to/admin-password \
python3 -m chatsite.web --host 127.0.0.1 --port 18082
```
