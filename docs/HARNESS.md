# WorkOS quality harness

Version 1.8.0, 2026-10-04. A harness is the execution surrounding a model: evidence access, tools, budgets, completion checks, review, repair and persistence. It improves inspectability and catches specific errors; it cannot guarantee factual truth or investment judgment.

## Execution

All 13 research-material recipes support fast and thorough modes. Fast drafts run deterministic acceptance checks. Thorough work runs generation → acceptance checks → a separate model review → one repair if blocking issues exist → fresh checks and review → save. Clean work uses two calls; repair work uses at most four. Review uses the selected provider in a separate call, not an independently trained model. The reviewer returns bounded JSON findings with exact draft quotes, severity, proposed fix and allowed source labels. Invalid reviewer output or remaining blocking issues fails closed. Warnings remain visible on a saved draft.

Checks distinguish explicit constraints from inferred defaults. They cover output completion, source labels, table structure/counts, unambiguous question/length/section requests, false full-read/DD claims and numerical period/currency/unit/nature labels. Source-label existence does not prove entailment. Rule extraction and semantic review can miss errors. `facts_verified` always remains false; editing the body invalidates the old report. No background browsing or factual certification is implied.

## DSH capability boundary

GPT thorough generation uses the installed [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) through the existing authenticated DSH CLI. Integration was exercised with 0.2.0-rc.2; upstream is a developer preview, so upgrades require the synthetic protocol and live canary checks again. WorkOS does not copy OAuth credentials or vendor the upstream runtime.

Only `workos_sources`, `workos_read_source`, `workos_find_evidence` and `workos_check_draft` are admitted by a global tool guard and per-agent allowlist. The model receives the selected source directory and accesses text through these tools. Arguments are source IDs/ranges/search terms/draft text, never paths or shell commands. Filesystem, shell, web, subagent, plugin/skill loading, ambient instructions, logging/title and telemetry plugins are disabled. Read-only sandbox configuration alone is not the evidence boundary; WorkOS tool validation enforces it.

Actual read intervals are merged per source, and repeated delivery counts against the 200000-character budget. There are at most128 calls, with final-check capacity reserved; the packet is capped at4million characters. Coverage reports tool-read text only and never treats one partial read as reading a complete file. The exact final draft must have passed the selected-source tool check. JSON completed-turn + final text + exit0 are all required. A trusted launcher closes residual Node handles only after DSH reports its own disposal exit code, never just because answer text appeared. Sessions, packet and captured events are removed with the disposable run directory. Other selected providers use the same WorkOS quality graph with bounded source excerpts instead of native DSH tools.

## Durable jobs and limits

`POST /api/workflows/jobs` accepts immutable requirements, selection, quality mode and a stable request ID. Acceptance returns quickly; GET lists/scoped snapshots support polling, navigation, reconnect and reload. Inputs are capped at12MB and at most80 documents; two workers handle at most eight active jobs. A provider-identity hash excludes API keys and is checked before every model call; credential rotation is allowed without persisting the key. Source/context edits block stale saving.

The local private job DB persists snapshots/checkpoints separately from personal/demo records. Startup recovers an already saved generation ID or marks unfinished work interrupted; retry requires an explicit action and revalidates captured inputs. This prevents a save/checkpoint crash from duplicating drafts. Release backups include the job DB. Record mirroring includes saved draft/reports but not unfinished jobs; restoring a record mirror alone does not resume jobs.

Shutdown marks unfinished jobs interrupted before closing the listener; late provider responses cannot save or change checkpoints. A blocked HTTP call may take its bounded timeout to return, but that old worker loses write authority immediately. Unknown submit fields are rejected, including credentials and caller-injected private guard metadata.

Native Excel calculations remain Python/formula-based and require their dedicated numerical validation. Meeting-transcript helper generation and simple research Q&A retain their existing bounded adapters; they do not implicitly perform the material workflow's independent critic cycle. Word/PPT exports are editable presentations of the draft, not a separate factual-validation stage. No automatic mail sending, arbitrary workbook editing, model-weight training or broad quality benchmark is claimed.

## One model selection across work

All AI surfaces resolve the same reviewed service/model pair. GPT uses DSH, while the compatible models keep their exact requested IDs. Agent JSON actions, meeting drafts and valuation assumptions now support either route; changing model within a scoped conversation keeps that scope. No model choice bypasses evidence boundaries, cancellation or deterministic valuation formulas. Plain GPT action/meeting/assumption calls do not gain arbitrary DSH tools. Synthetic JSON probes verify bounded completion for the selected route, not general factual quality or independently authenticated upstream identity.
