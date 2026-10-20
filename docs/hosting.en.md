# Private static hosting

ChatSite provides managed private sites and a CLI workflow from development to production. Public registration is closed. An administrator provisions accounts, registers sites, and grants explicit site permissions. Coolify manages application infrastructure; ChatSite manages this hosting product. Neither Coolify nor CI is required for this CLI workflow.

```sh
python -m pip install ChatSite
chatsite hosting login --url https://chat.example.com --username YOUR_ACCOUNT
chatsite hosting upload my-notes ./dist
# Review /sites/my-notes/dev/ and the returned immutable version.
chatsite hosting publish my-notes --release VERSION
chatsite hosting versions my-notes
chatsite hosting rollback my-notes --release PREVIOUS_VERSION
```

Every directory must contain `index.html`. Upload changes only development. Publish explicitly selects the reviewed release; rollback selects an earlier production release and leaves development unchanged. An optional short alias, such as `/my-notes/`, resolves the same production pointer. Publication asks for confirmation; `--yes` provides an explicit noninteractive override.

Use `/hosting/` to manage accounts, sites, grants and versions, or use `hosting users create`, `hosting create`, and `hosting grant`. Global owners/admins administer sites. Viewers read their assigned sites; publishers may also upload, publish and roll back. A new account has no implicit site access. Revoked grants apply immediately, and disabling an account revokes its sessions. Only the owner can provision an admin. Public registration returns403.

Server operators install `ChatSite[overleaf,hosting]`, bootstrap the first managed owner with `chatsite hosting bootstrap --username owner@example.test --password-env EXISTING_OWNER_PASSWORD`, and enable `CHATSITE_HOSTING_ENABLED=true` in the existing Hub process. Bootstrap is a server-side operation against an empty account directory, never a public API. Reusing the configured Hub owner identity/password also permits its existing session to access hosting. Other managed users sign in at `/hosting/login` and do not gain legacy Hub/Overleaf access.

Managed accounts and sessions use ChatLogin under ChatArch home. Hosting data defaults to `hosting/` inside the Hub data directory; `CHATSITE_HOSTING_DATA_DIR` overrides it. Client sessions use ChatEnv TokenStore; `--profile NAME` and `--home PATH` isolate client sessions. Passwords are not saved. For scripts, `--password-env KEY` names an environment variable. Sessions last one day; `hosting logout` revokes the selected session.

Every static resource checks live account and site permissions. Archives are bounded to32 MiB compressed,64 MiB expanded and2000 entries; traversal, symlinks, secret files, Git metadata, duplicate paths and encrypted entries are rejected. Sites retain up to200 releases without automatic deletion. Immutable releases and transactional channel pointers preserve production while development changes.

Site scripts run in a CSP sandbox by default, preventing same-origin account access; browser storage and same-origin fetch extensions are restricted. Only administrators may declare a site `--trusted` for fully trusted code and publishers that need these extensions. Trusted scripts share the management origin, so granting publishing access to such a site also grants code-level trust. Service Workers are blocked. See [browser sandbox semantics](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox).

The Python APIs are `HostingClient` in `chatsite.hosting_client` and `HostingStore` in `chatsite.hosting`. API routes live under `/api/hosting`; `/session` returns the current principal and CSRF. Cookie writes require CSRF and a permitted Origin; CLI uses explicit Bearer sessions, with redirects disabled. Dynamic integrations must check site permission and a separate management role, rather than treating any login as an administrator. Store dynamic data outside static releases.
