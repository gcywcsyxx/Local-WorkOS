# Public edition validation

Validation uses synthetic fixtures and independent temporary databases. No original user memory or actual model API credentials are read.

## Local results

### 1.6.1 selected-model ask on lexical misses, 2026-10-04

- Twelve real loopback HTTP regressions use synthetic provider responses: all four provider paths are invoked once on a lexical miss or empty text, keep the selected model, report actual model_called/retrieval_basis, and reject nonexistent source tags. Scope, memory, cross-workspace, model allowlists, CSRF, cancellation and no automatic save remain enforced. Generic requests longer than3000 characters now follow the documented4000-character limit.
- Eight pure context groups verify fair inclusion of late selected documents, deterministic head/middle/tail sampling, the24000-character total and900-character quote bounds, real quote/chunk/page/ordinal identity, empty text, invalid identities, deduplication and unchanged inputs. Strict local keyword retrieval stays separate from model reading.
- Chrome adds a no-hit model-response display/payload check: actual model identity, brief explanation and coverage warning, exact selected scope, no saved records and source opening. Browser/provider fixture responses are synthetic; these checks do not certify factual accuracy.

- A live source-only synthetic DeepSeek V4.1 Flash canary exercises a genuine lexical miss through the existing compatible bridge and returns an84-character, two-sentence Chinese answer with a real source tag. No runtime business records or personal sources are used. This validates dispatch and brief output for this case, not general factual quality.

### 1.6.0 Enter-send and stopping AI work, 2026-10-04

- Real HTTP and blocked-provider fixtures cover cancel before arrival/acknowledgement, queued/running durable jobs, late compatible-model output, DSH cancellation, agent partial commits, atomic meeting save, edited-meeting protection, cancel-vs-save ordering, terminal persistence after restart, workspace/CSRF/auth and bounded registries. No production model calls are used.
- Browser regressions exercise actual Enter/Shift+Enter, IME/key229 and key repeat, all research modes and homepage staging, retained drafts, new request identity, stop across navigation, pending task registration, queued/running jobs, failed stop and retry, late ask/action/meeting/valuation responses, normal editor newlines and mobile overflow.
- Eight isolated Node groups execute the real AI run/composer helpers and check old-result/finally ownership, per-run aborts, request IDs, retryable stop failures, unrelated work, context guards and keyboard behavior. Stopping cannot revoke an already accepted provider request; no late work is saved.

### 1.5.3 session recovery, 2026-10-04

- Real HTTP fixtures verify that stale CSRF rejection happens before writes, job creation or provider calls; Host/Origin, login and other permission failures cannot carry the recovery code.
- The isolated browser reproduces the valuation parser failure, refreshes its token once, sends an identical request once, and keeps the natural-language/JSON drafts and pending DOM. An ordinary permission failure is shown without refresh or retry.
- Transport tests cover concurrent refresh sharing, the retry limit, exact request preservation, invalid bootstrap data, workspace changes and aborts. Refreshing a token does not call full boot or reload the page. An already-open older client requires one page refresh to load this fix.
- A Windows CI run exposed an existing DSH fixture's three-second cold-start deadline. Lifecycle/protocol fixtures now allow startup time and assert the specific completion/parse failure rather than accepting any timeout; the dedicated timeout fixture keeps its short deadline. The lifecycle fixture retains a never-ending handle and checks that runtime disposal actually finishes. Production deadlines are unchanged.

### 1.5.2 homepage project creation, 2026-10-04

- 29 isolated Chrome/CDP groups pass, including creation from the homepage button/dropdown, cancel preserving the prior project/request, empty-name rejection, minimal creation automatically selected, retained workflow purpose, unchanged existing materials and research selections, plus desktop/375px layout.

### 1.5.0 harness revision, 2026-10-04

- 1.5.1 adds controlled shutdown/restart regressions with a blocked model: an old late response cannot save or overwrite a fresh process's retry/completed checkpoint. Extra submit fields cannot persist credentials.
- Synthetic quality fixtures cover all13 recipes, unambiguous constraints, table parsing, source labels, completion cutoffs and false full-read/DD/model-recalculation claims. Clean review does not set facts_verified. Integration verifies independent critic JSON, blocking repair/re-review, one-repair limit, visible warnings and stale checks after editing.
- Durable-job tests cover concurrent duplicate requests, workspace isolation, immutable evidence, memory conversion, project-context edits, bounded queue, restart interruption/retry, saved-generation checkpoint recovery, provider identity changes before/between calls and credential rotation without durable secret storage.
- Updated isolated Chrome groups cover quick acceptance, unlocked composer/navigation, actual stage snapshots, reload, disconnect/backoff, failed/interrupted retry, stable expanded quality cards, findings, stale edits and desktop/mobile overflow. Browser model responses are synthetic; no production records are modified.
- A real source-only synthetic GPT-6 Luna canary traversed installed DSH: source directory → actual source read → exact final draft check → completed turn/final/exit0. The trace recorded126/126 source characters. Disposable launcher lifecycle tests also reject failed disposal; budgets, trace spans, unselected sources and cancelled runs fail closed.
- A live synthetic thorough job traversed the existing compatible bridge, returned acceptance immediately, repaired a draft once, and saved only after a second review plus deterministic checks: exactly three data rows, one table and one follow-up question, actual/forecast labels and a valid source tag. The canary exposed a Chinese row/header constraint parsing gap, which was fixed and rerun; the final assert checks actual counts, not merely completed status.
- These are bounded acceptance and transport checks, not a broad factual-quality benchmark. Each deployment still runs the SOP suite and verifies the installed/source/remote revisions; remote CI is checked after push.

### 1.4.0 revision, 2026-10-04

- Complete Python unit/HTTP suite runs on isolated temporary data; covers automatic grouping/old-record migration, immutable originals and delayed mirror recovery, explicit-source recipes and model failures, request retry/concurrency/workspace cache boundaries, memory boundaries, typed-model reopen/recompute/saved XLSX, annual LBO economics and online SQLite WAL backups. Three Windows real-symlink tests are skipped; simulated reparse checks still run.
- 27 physical Chrome/CDP interaction groups passed using a new profile, synthetic records and mocked generation: home/project merge, single composer/drafts/scope, all material versions/subtasks/folder intake, recipe staging and saved drafts, source-less email, provider failure/retry IDs, meeting transcript protection, model restore/one-click scenario comparison, paste safety, citations and mobile overflow. Desktop/mobile screenshots were inspected; screenshot fixtures were not production records.
- 14 Markdown groups and five login recovery groups passed. Raw HTML and unsafe links remain inert.
- Three synthetic LBO workbooks were recalculated with the already configured native LibreOfficeKit, including direct edits to initial_cash/seller_rollover/exit_multiple/minimum_cash/cash_sweep_pct. All eight Summary metrics and each of four years' debt/cash/shortfall figures matched fresh Python results (relative tolerance 1e-8, absolute 1e-6); all 88 native formulas retained, no cached formula errors.
- A live synthetic research recipe traversed the existing compatible bridge, produced and saved a readable three-row financial table with actual/forecast distinction, a follow-up question and valid source citation. A first run exposed excess template sections; prompt precedence was corrected and rerun. No private materials were sent; this is a bounded smoke test, not a general quality benchmark or independent verification of the bridge's model identity.
- The release SOP separately verifies the installed version/commit, configured mirror, public account configuration, login page and anonymous API denial. Production passwords/cookies are not extracted. Remote Actions status is checked separately after push.

### Historical baseline

- 110 unit, storage, HTTP, parsing, retrieval, valuation, sync, DSH-boundary, memory-upload and export tests: 107 passed, 3 skipped because this Windows test account cannot create real symbolic links. Link/reparse rejection is also covered with simulated metadata tests.
- The 1.0.0 baseline passed eight Playwright workflow groups. For 1.3.0, headless Chrome rendered the research and valuation routes, confirmed the paste-import control, the four valuation methods, and that no per-request consent checkbox remains; Playwright is not installed here, so the full browser workflow suite was not rerun.
- 1.1.0 model smoke: a synthetic evidence question traversed Local WorkOS → DSH → GPT-6 Luna and returned one grounded citation. DSH tools, session-log, title and telemetry plugins were disabled; session persistence was redirected to a disposable temp directory. No personal materials were used.
- Nine pages at 390px: no root horizontal overflow; hidden sidebar did not receive keyboard focus. No browser console/page errors (1.0.0 baseline).
- Independently implemented report editor: default reading, selected-quote annotation, stable paragraph IDs, edited plain text, real HTML downloads, two fresh-context reopens and annotation deletion passed. Title/body/note/edit XSS probes remained inert; no external requests or page errors.
- Real two-page PDF extraction and DOCX parsing security limits are exercised by unit fixtures. Optional Word export is tested when python-docx is available.

## GitHub checks

The repository workflow runs the synthetic unit suite on Windows and Ubuntu with Python 3.11 and 3.12. Its actual status is visible under the repository Actions tab; local success is not represented as remote-CI success.

## Not claimed

A synthetic canary was sent through the integrated DSH → GPT-6 Luna route and returned the expected text; the unit suite uses a mocked model adapter and never sends fixtures to a live model. No broad answer-quality benchmark is claimed. No OCR, email/chat integrations, recordings, cloud sync, complete LBO or enterprise deployment tests are claimed. Evidence attribution does not validate the underlying source's truth.
## Research-first UI regression (no Playwright dependency)

```shell
node tests/test_markdown.cjs
node tests/test_api_client.cjs
node tests/test_ai_controls.cjs
node tests/browser_auth_client.cjs
node tests/browser_research_cdp.cjs
```

The Chrome/CDP test starts its own temporary Python instance and Chrome profile, seeds synthetic records, intercepts ask/agent responses, never calls real models, and stops only its created process trees. Use Node24 built-in fetch/WebSocket, Python in PATH or WORKOS_TEST_PYTHON, and Chrome installed or WORKOS_TEST_CHROME. It verifies merged home/project navigation, one composer/drafts/scope, readable Markdown/inert unsafe HTML, citation navigation, editable paste and narrow-screen overflow. Never substitute production 18866 or an existing private Chrome profile.
