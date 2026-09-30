# Public release privacy boundary

This repository contains application code, independently implemented report editing, synthetic demonstration data and synthetic tests. It does not contain the original user's memory, CV, actual work documents, databases, backups, logs, keys, computer inventory or personal file paths.

## Before publication

- Assemble a fresh code-only directory instead of publishing the original work folder or its Git history.
- Use neutral product branding and generic documentation.
- Exclude original screenshots, internal documentation and internal editor/skill assets.
- Disable all implicit memory-root discovery; require explicit configuration by each user.
- Exclude caches, data, databases, exports, credentials and logs through Git ignore rules.
- Audit the actual Git-tracked file list and text, not just the working directory.
- Use generic commit attribution, not a local real-name/email Git identity.
- Preserve required third-party copyright/license notices. Those public upstream notices are not the original user's private information.

## Ongoing responsibilities

Repository visibility does not make data entered into the app safe to share. Keep personal/runtime files out of commits. Markdown source filtering is best-effort; names, financial information or other sensitive content can remain after token filtering. Review report exports and backup files manually before sharing.

The app does not automatically send memory to a remote model. External research-model requests require selected documents and per-request consent. API keys are held in server memory, not source files or backups.

GitHub will still display the public repository owner's existing account and repository activity. A public repository cannot conceal its owner account; it can avoid adding private identity, documents and local-environment details to the published project.
