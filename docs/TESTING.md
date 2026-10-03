# Public edition validation

Validation uses synthetic fixtures and independent temporary databases. No original user memory or actual model API credentials are read.

## Local results

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
node tests/browser_auth_client.cjs
node tests/browser_research_cdp.cjs
```

The Chrome/CDP test starts its own temporary Python instance and Chrome profile, seeds synthetic records, intercepts ask/agent responses, never calls real models, and stops only its created process trees. Use Node24 built-in fetch/WebSocket, Python in PATH or WORKOS_TEST_PYTHON, and Chrome installed or WORKOS_TEST_CHROME. It verifies merged home/project navigation, one composer/drafts/scope, readable Markdown/inert unsafe HTML, citation navigation, editable paste and narrow-screen overflow. Never substitute production 18866 or an existing private Chrome profile.
