# Architecture

## Runtime

Python 3.11+ standard-library HTTP server and SQLite; native JavaScript/CSS, no frontend build pipeline or CDN. The launcher uses an existing Python interpreter and binds loopback only. Windows uses an exclusive listening socket to prevent shadowing an existing wildcard listener.

Records live in separate personal/demo SQLite files outside the source checkout. A lock protects operations, writes are persisted transactionally, and relation validation rejects broken/cross-project references. Deleting referenced records fails instead of silently cascading. Backup restore validates the complete snapshot, rejects cross-workspace restore, saves the previous database and replaces data transactionally.

## Shared objects

`projects → documents / meetings / tasks / notes / deliverables`

The UI reads one shared state endpoint rather than keeping separate disconnected dashboards. Research selections and meeting confirmations carry explicit project associations. Human confirmation is kept separate from unverified source content.

## Evidence and optional models

One reviewed `model_catalog.py` resolves exact canonical service/model identity for every AI surface. Bootstrap and GET expose the same grouped catalog without network calls. A cancellable POST synthetic JSON probe stores only nonsecret status in runtime `model-status.json`, with endpoint/model identity and24hour expiry; missing runtime wins over cache. Preset keys never inherit credentials configured for a different endpoint. Completion-only bridge entries are visible and disabled. The bridge catalog/echoed IDs do not independently authenticate actual upstream model identity.

PDF text retains actual page boundaries. TXT/Markdown/DOCX use ordinal chunk citations without invented page numbers. Stable chunk IDs and attributed excerpts support a source viewer.

Local retrieval is deterministic lexical matching, not a language model. Irrelevant questions can return no evidence. Both the DSH GPT and compatible routes use explicitly selected documents; memory is rejected before remote calls. DSH uses the existing authenticated CLI with disposable state. Ambient instructions and arbitrary filesystem/shell/web/subagent tools are disabled; the trusted plugin denies all names except four selected-evidence tools in thorough mode (no tools in the plain route). OAuth remains in DSH; custom keys stay in WorkOS memory. See [harness contract](<HARNESS.md>) for completion checks and limits.

The async UI posts to a separate local `workflow-jobs.sqlite3`. Two workers execute at most eight active jobs, reading frozen selected-evidence snapshots; each model call guards the nonsecret provider identity. Source/context changes block stale saving. `generation_id` on deliverables recovers a save interrupted before the job checkpoint. Startup marks unfinished jobs interrupted instead of silently rerunning. The synchronous endpoint remains supported. Job snapshots are private runtime data excluded from Git and the record mirror; release backups include the job DB. Saved `quality_report` travels with the draft; edits invalidate it.

## Memory boundary

Automatic memory discovery remains disabled unless an absolute `WORKOS_MEMORY_ROOT` folder is configured; there is no implicit home-directory, ancestor or cloud-folder discovery. In the personal workspace, the user may explicitly select TXT/MD/PDF/DOCX files or a folder in the browser. The server accepts only relative file paths, rejects hidden/credential/environment/archive components, sanitizes extracted text, stores read-only copies locally and never sends `kind=memory` to a model. Folder selection is capped; sanitization is best-effort, not a guarantee of complete anonymization.

## Deterministic finance

A simplified pre-tax equity return model computes debt, retained cash, terminal equity, IRR/MOIC and sensitivity in code. Scenarios keep entry consideration fixed. Positive cash repays debt then accumulates; deficits draw debt; terminal cash is counted only once. No intermediate distributions, detailed tax schedule or complete debt covenant model is claimed.

## Standalone reports

The public edition includes an independently implemented editor. User text is escaped, edits are plain text and annotation state is safely embedded in JSON. Saving downloads a standalone HTML copy; reopening reconstructs one UI and retains edits/notes without connecting to the platform database or external network.

## Security and limitations

Host/Origin checks, per-process CSRF token, bounded uploads, restricted static routes, safe DOCX ZIP/XML parsing and escaped UI text reduce local attack surfaces. The shell keeps a strict script CSP. These controls are not an enterprise multi-user authentication system. Other software running as the same local user is outside this prototype's isolation guarantees.

Future work is deliberately not presented as implemented: OCR, email/calendar integrations, recording, live collaboration, cloud sync, richer financial models and production deployment controls.
