# Local WorkOS — AI engineering handoff

Documentation date: 2026-10-04. Product version: 1.5.0. This document describes the quality harness, durable jobs, automatic organization and reloadable-model release.

Read [PRD](<PRD.md>) first. It distinguishes implemented features, verified behavior and proposed additions. Earlier [README](<../README.md>), [architecture](<ARCHITECTURE.md>) and [testing](<TESTING.md>) descriptions can lag current code; do not remove password auth, editable PPTX or four valuation methods based on historical wording.

## Source vs install vs data
- The repository root is editable development source and the Git working tree.
- Windows installation is `%LOCALAPPDATA%/Programs/LocalWorkOS/1.5.0/<build>`. Changes in a source checkout are not hot-reloaded there. Preserve/update the existing startup shortcut when changing the install version.
- Runtime personal/demo SQLite, authentication and logs are under `%LOCALAPPDATA%/LocalWorkOS`, never in source control.
- OneDrive is an optional JSON/text mirror and backup target, not the live SQLite/WAL database or a bidirectional multi-master store.
- Remote access reaches one authoritative host through its dedicated tunnel; keep that host running and online. Do not attach divergent databases/sessions to the same tunnel from two machines.
- This public repository does not contain deployment-machine paths, business records, passwords, sessions, API keys or Cloudflare credentials.

## Files to read

| File | Purpose |
|---|---|
| [server](<../workos/server.py>) | HTTP routes, authentication, Host/Origin/CSRF, model adapters, upload/export |
| [jobs](<../workos/jobs.py>) | Durable jobs, frozen inputs, restart recovery, idempotent save |
| [quality](<../workos/quality.py>) | Acceptance checks, critic schema and repair brief; no truth certification |
| [DSH adapter](<../workos/dsh_harness.py>) | Completion/exit checks and disposable scoped tool execution |
| [harness contract](<HARNESS.md>) | Quality modes, evidence ledger, compatibility and limitations |
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
The original [requirements](<../requirements.txt>) only declare the historical Word dependency. Use [development dependencies](<../requirements-development.txt>) for the full current test/export suite; CI now installs this full file. A locally passing suite is not proof of a successful remote CI run.

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
1. New research uploads retain immutable original bytes in data_dir/originals/{workspace}/{sha256}, with authenticated downloads and OneDrive copying/recovery. Older records cannot recover original bytes without reupload. JSON backups exclude original bytes; OneDrive mirrors include them. No automatic scanned-PDF OCR; Excel cached values may be stale.
2. Saved valuation deliverables persist method/assumptions/result; Store recomputes result on save/update/restore. UI restores a model for continued calculation/scenarios, and saved-record XLSX export regenerates linked formulas. Older body-only snapshots remain readable but cannot be assumed reloadable. Imported complex Excel is extracted for source-based review; it is not automatically rewritten or recalculated.
3. Citations locate extracted excerpts; [S#] number validation is not semantic support or fact verification. Extracted text remains editable even though uploaded originals are immutable; citations have not been changed into immutable version anchors.
4. The bounded assistant can organize projects, create subtasks, run explicit-source recipes and draft selected meeting minutes. It does not execute arbitrary files/shell, send email or modify an imported workbook. Recipe prompts are execution rules, not training of model weights.
5. Sync has no live bidirectional merge, periodic pull or stale-file reconciliation; last_sync is a local write time, not proof of cloud upload.
6. A full IC story, templates, three-statement integration, debt tranches/interim dividends/dilution are not implied by an editable file export.
7. Global paste now preserves all editable fields. Keep the browser regression: normal input/textarea/contenteditable paste must not create a document. The research page has one composer with explicit ask/action modes, not duplicated forms.

## Feature modification patterns
- Data additions: update [Store](<../workos/store.py>) schema/defaults/validation and test older records plus backup/restore. Meeting structured fields must have valid dimensions/indices; changing only summary intentionally invalidates stale structures.
- [Organization](<../workos/organization.py>) derives task_group/material_type/version_family/version_label locally from bounded filename/content evidence. Store runs it on create/update/startup/restore and custom subtask changes. Explicit task_group is a manual override; clearing it resumes automation. No new collection was added, so old version-1 backup topology remains valid. Never include memory or execute source instructions. Version families are project-scoped; recent import order is not semantic approval or finality.
- [Attachments](<../workos/attachments.py>) validates workspace and hash-only paths, verifies hashes on download/restore and keeps original bytes independent of edited text. Mirror sync deduplicates hashes and caches stat signatures to skip unchanged immutable originals during normal saves. Missing mirror originals are retried on subsequent sync; status counts missing bytes by workspace.
- Model edits: keep arithmetic in [valuation](<../workos/valuation.py>), then update exporter/UI/tests. Validate unit/period/ranges/missing/finite values. Actually recalculate edited workbooks and compare against Python, not only inspect formula strings. Snapshot columns remain labeled as original input results.
- NL parsing currently uses allowed DSH GPT models. A local compatible bridge is not proof of offline inference or model entitlement. Model errors must remain explicit.
- PPT native tables/charts use [documented data blocks](<pptx-export.md>); preserve all rows/content or reject excessive output explicitly. Word TOC uses real bookmarked PAGEREF fields, not guessed page offsets.
- Preserve regression tests for original-file persistence, automatic version grouping, workflow source coverage, saved typed-model reload and formula XLSX export. Immutable citation anchors remain pending: extracted text can still change.

## Authentication and privacy contracts
Use [password deployment guide](<password-public.md>) for password mode and [Access guide](<cloudflare-access.md>) only when that mode is chosen.
Keep authentication on all remote workspace APIs/downloads, session CSRF, Host/Origin checks, nonce/cookie binding, fresh-before-submit challenges and IP-based throttling (not strict IP binding), login rate limits and local-only setup. Forwarded localhost must not become an anonymous bypass. Passwords remain salted hashes, session IDs hashed and local; never export them into backups, mirrors or source.
The source default closes public access; a specific deployment opts into HTTPS password mode. Single account is not enterprise RBAC. Localhost bypass is deliberate for the trusted host owner.
Keep kind=memory out of every model call. Never extract browser cookies or place tokens into docs, commands or repository remotes. Use only existing saved credentials; do not open auth popups automatically.

## Publishing safely
When the user requests publication, that instruction authorizes the release below; do not request the same approval again. Back up business records, inspect the diff and run isolated tests. Do not delete/move runtime data, authentication files or shared tunnel configuration. Installation copies tracked source into a separate stable directory and records its commit in the running health endpoint.

```powershell
# Source checkout; point to a verified existing Python with the needed dependencies
./tools/release.ps1 -Python "<existing-python-path>" -CommitMessage "Describe reviewed change" -Publish -Push
```

Stop/restart the current app through its supported launcher when releasing. Use [public starter](<../tools/start_public.py>) only with the deployment-owned dedicated UUID/config and password-protected origin. New code on OneDrive or GitHub is not proof that the running service was updated. New machines must provision authorized local runtime independently and must not run a second conflicting write authority.
The SOP runs isolated Python, Markdown, authentication-client and Chrome/CDP tests; checks public-source privacy/history; commits reviewed source; backs up committed SQLite including WAL; installs and retargets only an existing authorized startup shortcut; restarts the app; verifies local version/commit, mirror status, public login and anonymous API denial; then pushes and compares remote SHA. Authentication/session/CSRF/logout persistence are exercised with synthetic credentials in tests. Read-only production probes do not obtain real cookies/passwords and do not claim an actual authenticated human login. The tunnel starter reuses the configured dedicated connector. Do not print credentials or cookie/CSRF values.

## Work recipes and coverage
[workflows](<../workos/workflows.py>) contains research brief, DD, IC Memo, discussion material, technology explainer, agreement review, interview preparation, expert-network request, email, project update, version comparison, model review and tabular meeting synthesis. Home planning is deterministic and sends no material; generation uses the selected provider and explicitly selected sources. Every selected document receives a bounded excerpt and a coverage entry. Reject missing sources, memory, cross-project records, empty answers and invalid citation labels before saving a deliverable. Local excerpt mode must never silently call an external model. Preserve requested audience, language, page count and purpose. Separate source facts, management forecasts, independent expert views and team assumptions.

Workflow requests use a workspace-scoped request_id: same payload retries return the same saved draft, an in-flight retry returns workflow_busy/409, changed payload reuse is rejected and a provider failure permits retry. The cache contains the latest 32 successful requests and clears on process restart; it is not a permanent generation ledger. The UI retains the token across network retries and creates a new one when task/provider/source versions change. Compatible provider calls use a 95-second timeout; busy DSH calls reject rather than queue indefinitely. Longer background jobs and durable idempotency remain future work.

Future priorities are immutable citation anchors, evidence/issue reconciliation, full template-based presentation production and imported-workbook editing/recalculation. These are not implied by current exports. Update PRD and handoff with implemented/pending status and verification evidence on every significant delivery; local tests do not prove remote CI or visual fidelity of every generated artifact.
