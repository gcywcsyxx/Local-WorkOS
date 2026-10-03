# Password-protected public WorkOS

The user-selected password mode is separate from Cloudflare Access. The origin listens only on 127.0.0.1; a dedicated cloudflared tunnel forwards HTTPS requests.

## Configuration
- `WORKOS_PUBLIC_AUTH_MODE=password` (default remains `access`).
- `WORKOS_PUBLIC_ORIGIN=https://workos.example.com`.
- `WORKOS_TUNNEL_ID`: the dedicated tunnel UUID.
- `WORKOS_TUNNEL_CONFIG`: local dedicated connector YAML, matching the UUID.
- `WORKOS_SYNC_ROOT`: existing OneDrive file-mirror directory, never an active SQLite location.

Start using `tools/start_public.py` from the installed app. It launches the application without opening a browser, verifies password enforcement and the origin configuration, and starts only the matching dedicated tunnel. It does not modify shared tunnels.

## Account
New installations default to `workos-user`. Existing configured accounts retain their username, password hash and sessions; enter that username on the public login page. Set/change the password at `http://127.0.0.1:18866/auth/setup` on the host computer; the endpoint is forbidden through the tunnel even if Host is rewritten to localhost. This setup endpoint requires the local CSRF token. Password minimum 8 characters, recommended 12+; do not reuse a disclosed or shared password. Only the PBKDF2-SHA256 600,000-iteration salted hash is stored.

Password hashes and hashed session identifiers are under the local application data directory, separate from OneDrive mirrors and repository source. No plaintext password or raw session token is persisted. Change/reset from the host computer invalidates existing sessions.

## Remote sessions
All remote workspace API and download routes require an authenticated session. Anonymous browser navigation redirects to `/auth/login`; anonymous APIs return 401. Sessions use Secure, HttpOnly, host-only cookies. Remembered sessions last 7 days and survive application restarts; unremembered sessions last 12 hours. Each session has its own CSRF token. Login is nonce/cookie-bound, same-origin HTTPS-only, and rate-limited. Settings offers remote logout.

## Verify
- HTTPS `/` must redirect anonymous visitors to the login page.
- `/api/bootstrap`, `/api/state`, backups and exports must not reveal any private data without login.
- Correct credentials must permit the UI and APIs; wrong credentials, forged cookies and cross-site requests must be rejected.
- Hashes/session files must never appear in backups, mirror snapshots or public Git commits.
- Windows startup must preserve the dedicated connector config and authentication mode.
