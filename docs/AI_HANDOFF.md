# Local WorkOS — AI engineering handoff

Documentation date: 2026-10-03. Product version: 1.3.0. Implementation baseline: a41728d. The documentation commit may be newer.

Read [PRD](<PRD.md>) first. It distinguishes implemented features, verified behavior and proposed additions. Earlier [README](<../README.md>), [architecture](<ARCHITECTURE.md>) and [testing](<TESTING.md>) descriptions can lag current code; do not remove password auth, editable PPTX or four valuation methods based on historical wording.

## Source vs install vs data
- The repository root is editable development source and the Git working tree.
- Windows installation is `%LOCALAPPDATA%/Programs/LocalWorkOS/1.3.0`. Changes in a source checkout are not hot-reloaded there.
- Runtime personal/demo SQLite, authentication and logs are under `%LOCALAPPDATA%/LocalWorkOS`, never in source control.
- OneDrive is an optional JSON/text mirror and backup target, not the live SQLite/WAL database or a bidirectional multi-master store.
- Remote access reaches one authoritative host through its dedicated tunnel; keep that host running and online. Do not attach divergent databases/sessions to the same tunnel from two machines.
- This public repository does not contain deployment-machine paths, business records, passwords, sessions, API keys or Cloudflare credentials.

## Files to read

| File | Purpose |
|---|---|
| [server](<../workos/server.py>) | HTTP routes, authentication, Host/Origin/CSRF, model adapters, upload/export |
| [store](<../workos/store.py>) | Allowed fields/defaults/type checks, associations, SQLite transactions, backups |
| [engine](<../workos/engine.py>) | Safe text extraction, chunks, lexical retrieval/citations, legacy calculations |
| [valuation](<../workos/valuation.py>) | Four deterministic methods and typed assumption schemas |
| [exports](<../workos/exports.py>) | DOCX, dynamic Word page references, formula XLSX and editable PPTX |
| [deck blocks](<../workos/deck_blocks.py>) | Explicit Markdown tables and validated chart JSON, no execution or missing-value inference |
| [agent](<../workos/agent.py>) | Eight bounded actions, at most six steps |
| [password auth](<../workos/password_auth.py>) | Current public username login, local salted hashes, persistent opaque sessions, throttling |
| [Access auth](<../workos/access_auth.py>) | Optional legacy JWT verification; not required for password mode |
| [sync](<../workos/sync.py>) | Atomic outward mirror, previous revisions and empty-database restore |
| [memory](<../workos/memory.py>) | Read-only memory import/filtering and model-call privacy boundary |
| [main UI](<../web/app.js>) / [valuation UI](<../web/valuation.js>) | State, research/meeting/model workflow and export buttons |
| [auth UI](<../web/auth.js>) / [login](<../web/login.html>) | Same-origin login and local-only password setup |
| [launcher](<../launch.py>) | Stable startup, saved non-secret WORKOS settings and approved Office runtime paths |
| [installer](<../tools/install.ps1>) / [public starter](<../tools/start_public.py>) | Separate Windows deployment and idempotent dedicated connector startup |
| [tests](<../tests/>) | Synthetic, isolated HTTP/SQLite, exports, model formulas and authentication regressions |

## Full development dependencies
The original [requirements](<../requirements.txt>) only declare the historical Word dependency. Use [development dependencies](<../requirements-development.txt>) for the full current test/export suite. The existing CI workflow still installs only the historical file; updating CI is an explicit PRD follow-up, not claimed as completed here.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-development.txt
$env:PYTHONPATH = "$PWD/vendor"
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:WORKOS_SYNC_ROOT = ""
$env:WORKOS_MEMORY_ROOT = ""
$env:WORKOS_PUBLIC_ORIGIN = ""
$env:WORKOS_PUBLIC_AUTH_MODE = "access"
.venv/Scripts/python.exe -m unittest discover -s tests -q
```

Core HTTP/SQLite and password mode use stdlib. The [vendor PDF parser](<../vendor/pypdf/>) is included. Existing authorized DSH/compatible bridges and the approved bundled LibreOfficeKit/Node are external host runtime prerequisites, not included credentials. Do not search/install substitute Office renderers as an unreviewed fallback.

## Safe development
Do not use the launcher to create a development instance on a deployment host: it can reuse production 18866 and restore saved public/sync settings. Start the server directly on a free alternate port and an isolated temporary data directory.

```powershell
$testData = Join-Path $env:TEMP ("WorkOS-test-" + [guid]::NewGuid().ToString("N"))
.venv/Scripts/python.exe -m workos.server --port 18867 --data-dir $testData
```

Use synthetic data and mocked model responses. If the port is occupied, choose another rather than stopping unrelated processes. Browser scripts use WORKOS_E2E_URL or WORKOS_TEST_URL according to the script; read [TESTING](<TESTING.md>) before execution. For Host/security tests use raw HTTP headers (http.client); some fetch clients rewrite the reserved Host header.

## Verified limitations to preserve in requirements
1. Upload retains extracted text/chunks/hash, not original bytes. Attachment fields are placeholders; raw-file storage, immutable versions and authenticated original downloads are proposed additions. No automatic scanned-PDF OCR; Excel cached values may be stale.
2. Save Model embeds assumptions/result JSON in deliverable.body. Store does not yet support typed model fields; the saved-record XLSX route expects method/assumptions that these snapshots lack. Direct current-assumption POST /api/model/export-xlsx works.
3. Citations locate extracted excerpts; [S#] number validation is not semantic support or fact verification. Sources are mutable, not immutable original-file/version anchors.
4. The eight-tool assistant does not yet directly execute every valuation/minutes/export step.
5. Sync has no live bidirectional merge, periodic pull or stale-file reconciliation; last_sync is a local write time, not proof of cloud upload.
6. A full IC story, templates, three-statement integration, debt tranches/interim dividends/dilution are not implied by an editable file export.
7. Global paste now preserves all editable fields. Keep the browser regression: normal input/textarea/contenteditable paste must not create a document. The research page has one composer with explicit ask/action modes, not duplicated forms.

## Feature modification patterns
- Data additions: update [Store](<../workos/store.py>) schema/defaults/validation and test older records plus backup/restore. Meeting structured fields must have valid dimensions/indices; changing only summary intentionally invalidates stale structures.
- Model edits: keep arithmetic in [valuation](<../workos/valuation.py>), then update exporter/UI/tests. Validate unit/period/ranges/missing/finite values. Actually recalculate edited workbooks and compare against Python, not only inspect formula strings. Snapshot columns remain labeled as original input results.
- NL parsing currently uses allowed DSH GPT models. A local compatible bridge is not proof of offline inference or model entitlement. Model errors must remain explicit.
- PPT native tables/charts use [documented data blocks](<pptx-export.md>); preserve all rows/content or reject excessive output explicitly. Word TOC uses real bookmarked PAGEREF fields, not guessed page offsets.
- Test original-file persistence, reloadable typed models and versioned citations as new functionality rather than assuming placeholders already work.

## Authentication and privacy contracts
Use [password deployment guide](<password-public.md>) for password mode and [Access guide](<cloudflare-access.md>) only when that mode is chosen.
Keep authentication on all remote workspace APIs/downloads, session CSRF, Host/Origin checks, nonce/cookie binding, fresh-before-submit challenges and IP-based throttling (not strict IP binding), login rate limits and local-only setup. Forwarded localhost must not become an anonymous bypass. Passwords remain salted hashes, session IDs hashed and local; never export them into backups, mirrors or source.
The source default closes public access; a specific deployment opts into HTTPS password mode. Single account is not enterprise RBAC. Localhost bypass is deliberate for the trusted host owner.
Keep kind=memory out of every model call. Never extract browser cookies or place tokens into docs, commands or repository remotes. Use only existing saved credentials; do not open auth popups automatically.

## Publishing safely
Get approval for live release timing, back up business records, inspect the diff and run isolated tests. Do not delete/move runtime data, authentication files or shared tunnel configuration. Installation copies source into a separate stable directory.

```powershell
# Source checkout; point to a verified existing Python with the needed dependencies
./tools/install.ps1 -Python "<existing-python-path>"
```

Stop/restart the current app through its supported launcher when releasing. Use [public starter](<../tools/start_public.py>) only with the deployment-owned dedicated UUID/config and password-protected origin. New code on OneDrive or GitHub is not proof that the running service was updated. New machines must provision authorized local runtime independently and must not run a second conflicting write authority.
After release verify local health, mirror status, anonymous denial, authenticated UI/API, CSRF enforcement, logout and remembered-session persistence. Do not print credentials or cookie/CSRF values. Verify the pushed remote SHA before claiming GitHub is current.

## Suggested next task
For saved-model re-export, change Store typed persistence + UI save/load + server route while preserving legacy body snapshots, then test save → restart → load → edit scenario → deterministic recalculate → XLSX. Follow the prioritized backlog in [PRD](<PRD.md>).
Update PRD and handoff with implemented/pending status and evidence on every significant delivery. Current baseline local suite: 160 tests, 157 passed/3 skipped; not proof of a green CI run or image-based visual QA.
