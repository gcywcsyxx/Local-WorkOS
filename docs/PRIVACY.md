# Public release privacy boundary

This repository contains application code, independently implemented report editing, synthetic demonstration data and synthetic tests. It does not contain the original user's memory, CV, actual work documents, databases, backups, logs, keys, computer inventory or personal file paths.

## Before publication

- Assemble a fresh code-only directory instead of publishing the original work folder or its Git history.
- Use neutral product branding and generic documentation.
- Exclude original screenshots, internal documentation and internal editor/skill assets.
- Disable all implicit memory-root discovery; require explicit configuration by each user.
- Exclude caches, data, databases, exports, credentials and logs through Git ignore rules.
- Audit the actual Git-tracked file list and text, not just the working directory.
- Use the repository owner’s verified GitHub username and GitHub-provided noreply email for commit attribution; never invent an address that could belong to another account.
- Preserve required third-party copyright/license notices. Those public upstream notices are not the original user's private information.

## Ongoing responsibilities

Run `python tools/check_public_privacy.py --history` before publishing. CI repeats this check on the full reachable history. It rejects common credential formats, personal home paths, private runtime files and non-noreply commit emails without printing matched values. For owner-specific names or domains, add private local denylist entries with `git config --add privacy.blockedLiteral VALUE`; never commit that list. Keep independently auditing with a dedicated secret scanner, because these checks cannot guarantee detection of every secret format or remove old cached GitHub views.

Repository visibility does not make data entered into the app safe to share. Keep personal/runtime files out of commits. Markdown source filtering is best-effort; names, financial information or other sensitive content can remain after token filtering. Review report exports and backup files manually before sharing.

Imported memory is a local-only record: users explicitly pick files/folders, original files are never modified, and memory is rejected from every model request. Selected memory copies stay in the personal SQLite database; text filtering is best-effort. External research-model requests use the user’s current document selection as their scope: no separate per-request consent prompt is shown, and nothing outside the checked selection is sent. The DSH path reuses the existing DSH-managed account without copying OAuth tokens; its local model tools, session logging/title/telemetry are disabled and the per-request session store, overlay and answer are removed from a disposable system-temp directory after completion. The selected evidence is still sent to the remote model provider under that provider account’s data-handling terms. Custom API keys remain in WorkOS server memory, not source files or backups.

GitHub will still display the public repository owner's existing account and repository activity. A public repository cannot conceal its owner account; it can avoid adding private identity, documents and local-environment details to the published project.
