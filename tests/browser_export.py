"""Optional Playwright/installed Chrome regression; temporary synthetic data only.

Run with an existing optional Playwright environment; no dependencies are installed.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from playwright.sync_api import sync_playwright
from workos.exports import html_report


def main():
    attack = '</script><img src=x onerror="window.syntheticXSS=1"><script>window.syntheticXSS=1</script>'
    note_text = '合成批注：核对口径。' + attack
    edited = '修改后的合成正文。' + attack
    with TemporaryDirectory(prefix='local-workos-export-test-') as directory:
        output = Path(directory)
        source = output / 'synthetic.html'
        source.write_text(html_report({'title': '合成报告 ' + attack,
                                      'body': '## 证据核对\n模拟原文，等待进一步核实。\n第二段可修改。\n' + attack}), encoding='utf-8')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe', headless=True)
            errors = []
            requests = []
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.goto(source.as_uri())
            page.wait_for_function('window.LocalWorkOSReport')
            assert page.locator('#report-editor-ui').count() == 1
            assert page.locator('[contenteditable]').count() == 0
            assert not page.evaluate('Boolean(window.syntheticXSS)')
            assert page.locator('#body img, #body script').count() == 0
            page.locator('#report-edit').click()
            page.evaluate("""() => {
                const node = document.getElementById('p1').firstChild;
                const range = document.createRange();
                range.setStart(node, 0); range.setEnd(node, 4);
                const selection = window.getSelection();
                selection.removeAllRanges(); selection.addRange(range);
                document.dispatchEvent(new Event('selectionchange'));
            }""")
            assert page.locator('#report-selected-quote').inner_text() == '模拟原文'
            page.locator('#report-note-text').fill(note_text)
            page.locator('#report-add-note').click()
            assert page.locator('.report-note blockquote').inner_text() == '模拟原文'
            assert page.locator('.report-note p').inner_text() == note_text
            page.locator('#p1').fill(edited)
            page.locator('#p2').fill('第二段已修改。')
            with page.expect_download() as download:
                page.locator('#report-save').click()
            saved = output / 'saved.html'
            download.value.save_as(str(saved))
            saved_html = saved.read_text(encoding='utf-8')
            assert '<aside' not in saved_html
            assert 'contenteditable=' not in saved_html
            assert attack not in saved_html
            assert '\\u003c/script\\u003e' in saved_html
            assert saved_html.count('id="report-editor-script"') == 1
            assert saved_html.count('id="report-notes-data"') == 1
            fresh_context = browser.new_context(accept_downloads=True)
            other = fresh_context.new_page()
            other.on('pageerror', lambda error: errors.append(str(error)))
            other.on('request', lambda request: requests.append(request.url))
            other.goto(saved.as_uri())
            other.wait_for_function('window.LocalWorkOSReport')
            assert other.locator('#report-editor-ui').count() == 1
            assert other.locator('[contenteditable]').count() == 0
            assert other.locator('#p1').inner_text() == edited
            assert other.locator('#p2').inner_text() == '第二段已修改。'
            assert other.locator('.report-note blockquote').inner_text() == '模拟原文'
            assert other.locator('.report-note p').inner_text() == note_text
            state = other.locator('#report-notes-data').text_content()
            assert '"paragraphId":"p1"' in state
            assert not other.evaluate('Boolean(window.syntheticXSS)')
            assert other.locator('img').count() == 0
            # A second save/reopen must not accumulate UI or inline runtimes.
            with other.expect_download() as download:
                other.locator('#report-save').click()
            second = output / 'saved-again.html'
            download.value.save_as(str(second))
            third_context = browser.new_context()
            third = third_context.new_page()
            third.on('pageerror', lambda error: errors.append(str(error)))
            third.goto(second.as_uri())
            third.wait_for_function('window.LocalWorkOSReport')
            assert third.locator('#report-editor-ui').count() == 1
            assert third.locator('#report-editor-script').count() == 1
            assert third.locator('.report-note').count() == 1
            third.locator('#report-edit').click()
            third.locator('.report-note button').click()
            assert third.locator('.report-note').count() == 0
            assert not errors, errors
            assert all(url.startswith('file:') for url in requests), requests
            browser.close()
    print('PASS: default read/edit, selected quote + stable ID, text edits, actual HTML downloads, two fresh-context reopens, note deletion, XSS inert, no network/page errors.')


if __name__ == '__main__':
    main()
