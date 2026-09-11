# ChatImg Image Workbench

`chatsite image` runs ChatImg text-to-image as a dedicated Web entry point while reusing the shared ChatLogin page and session model.

## Interaction boundary

- Guests can generate images without signing in.
- Sign-in is optional. Signed-in users can open history owned only by their account.
- Anonymous history is never reassigned after login, and legacy generated-file URLs remain readable.
- An invalid or expired cookie is not silently downgraded; the page explicitly offers **Continue as guest**.
- The current surface is text-to-image only. It does not expose placeholder editing, multi-turn, or room controls.

The page preserves the established ChatImg logo, prompt suggestions, model/size/quality controls, staged progress, elapsed time, result metadata, downloads, and ChatShare flow.

## Configure and serve

Image registers the ChatEnv provider `chatsite_image`. Configure the public URL, data directory, administrator account, and ChatImg provider/profile in a ChatEnv profile; keep sensitive values out of commands and source files.

```bash
chatenv new web -t chatsite_image -I --yes
chatsite image check --profile web
chatsite image serve --profile web --host 127.0.0.1 --port 8766
```

`check` validates configuration only. It does not call the model or generate an image. In production, let the existing service supervisor own `serve`; do not start a second default instance.

Common keys:

- `CHATSITE_IMAGE_PUBLIC_URL`
- `CHATSITE_IMAGE_DATA_DIR`
- `CHATSITE_IMAGE_ADMIN_EMAIL`
- `CHATSITE_IMAGE_ADMIN_PASSWORD`
- `CHATSITE_IMAGE_PROVIDER`
- `CHATSITE_IMAGE_PROFILE`
- `CHATSITE_IMAGE_ALLOWED_ORIGINS`
- `CHATSITE_IMAGE_LEGACY_GENERATED_DIR`

## Data and security

- New images are written under `generated/` in the Image data directory.
- History metadata is stored in `history.sqlite3` and isolated by normalized account owner.
- `CHATSITE_IMAGE_LEGACY_GENERATED_DIR` provides read-only compatibility for old files; it does not assign anonymous records to a user.
- Generation uses bounded client throttling and does not trust browser-supplied forwarding headers.
- Login, logout, history, and generation writes use ChatLogin sessions and CSRF checks; JSON responses use `no-store` and `nosniff`.
