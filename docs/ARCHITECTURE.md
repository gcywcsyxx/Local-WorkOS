# Architecture

## Runtime

Python 3.11+ standard-library HTTP server and SQLite; native JavaScript/CSS, no frontend build pipeline or CDN. The launcher uses an existing Python interpreter and binds loopback only. Windows uses an exclusive listening socket to prevent shadowing an existing wildcard listener.

Records live in separate personal/demo SQLite files outside the source checkout. A lock protects operations, writes are persisted transactionally, and relation validation rejects broken/cross-project references. Deleting referenced records fails instead of silently cascading. Backup restore validates the complete snapshot, rejects cross-workspace restore, saves the previous database and replaces data transactionally.

## Shared objects

`projects → documents / meetings / tasks / notes / deliverables`

The UI reads one shared state endpoint rather than keeping separate disconnected dashboards. Research selections and meeting confirmations carry explicit project associations. Human confirmation is kept separate from unverified source content.

## Evidence and optional models

PDF text retains actual page boundaries. TXT/Markdown/DOCX use ordinal chunk citations without invented page numbers. Stable chunk IDs and attributed excerpts support a source viewer.

Local retrieval is deterministic lexical matching, not a language model. Irrelevant questions can return no evidence. Both the local DSH GPT route and optional OpenAI-compatible route take the current document selection as their scope, without a separate document selection and per-request external authorization. Imported memory is rejected before any remote call. DSH GPT runs through the existing authenticated DSH CLI using a per-request overlay; its tool plugins, session-log/title/telemetry plugins are disabled, and its session store, overlay and captured answer live in a disposable system-temp directory removed after the response. OAuth credentials remain in DSH; custom API keys stay in WorkOS server memory and are excluded from bootstrap responses and backups.

## Memory boundary

Automatic memory discovery remains disabled unless an absolute `WORKOS_MEMORY_ROOT` folder is configured; there is no implicit home-directory, ancestor or cloud-folder discovery. In the personal workspace, the user may explicitly select TXT/MD/PDF/DOCX files or a folder in the browser. The server accepts only relative file paths, rejects hidden/credential/environment/archive components, sanitizes extracted text, stores read-only copies locally and never sends `kind=memory` to a model. Folder selection is capped; sanitization is best-effort, not a guarantee of complete anonymization.

## Deterministic finance

A simplified pre-tax equity return model computes debt, retained cash, terminal equity, IRR/MOIC and sensitivity in code. Scenarios keep entry consideration fixed. Positive cash repays debt then accumulates; deficits draw debt; terminal cash is counted only once. No intermediate distributions, detailed tax schedule or complete debt covenant model is claimed.

## Standalone reports

The public edition includes an independently implemented editor. User text is escaped, edits are plain text and annotation state is safely embedded in JSON. Saving downloads a standalone HTML copy; reopening reconstructs one UI and retains edits/notes without connecting to the platform database or external network.

## Security and limitations

Host/Origin checks, per-process CSRF token, bounded uploads, restricted static routes, safe DOCX ZIP/XML parsing and escaped UI text reduce local attack surfaces. The shell keeps a strict script CSP. These controls are not an enterprise multi-user authentication system. Other software running as the same local user is outside this prototype's isolation guarantees.

Future work is deliberately not presented as implemented: OCR, email/calendar integrations, recording, live collaboration, cloud sync, richer financial models and production deployment controls.
