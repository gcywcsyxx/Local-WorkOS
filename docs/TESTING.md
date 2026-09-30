# Public edition validation

Validation uses synthetic fixtures and independent temporary databases. No original user memory or actual model API credentials are read.

## Local results

- 97 unit, storage, HTTP, parsing, retrieval, financial and export tests: 94 passed, 3 skipped because this Windows test account cannot create real symbolic links. Link/reparse rejection is also covered with simulated metadata tests.
- Eight real browser workflow groups passed: project/task CRUD, research/citation/deliverable/download, meeting action confirmation and duplicate prevention, changed financial assumptions, refresh/workspace/search/memory boundary, delete/unsaved-cancel dialogs, all mobile routes and browser console.
- Nine pages at 390px: no root horizontal overflow; hidden sidebar did not receive keyboard focus. No browser console/page errors.
- Independently implemented report editor: default reading, selected-quote annotation, stable paragraph IDs, edited plain text, real HTML downloads, two fresh-context reopens and annotation deletion passed. Title/body/note/edit XSS probes remained inert; no external requests or page errors.
- Real two-page PDF extraction and DOCX parsing security limits are exercised by unit fixtures. Optional Word export is tested when python-docx is available.

## GitHub checks

The repository workflow runs the synthetic unit suite on Windows and Ubuntu with Python 3.11 and 3.12. Its actual status is visible under the repository Actions tab; local success is not represented as remote-CI success.

## Not claimed

Real external-model reasoning was not configured or evaluated. No OCR, email/chat integrations, recordings, cloud sync, complete LBO or enterprise deployment tests are claimed. Evidence attribution does not validate the underlying source's truth.
