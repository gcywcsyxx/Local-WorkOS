"""Headless synthetic UI workflow checks against the isolated E2E server.
Run with testdeps on PYTHONPATH; never scans personal memory or calls a model.
"""
import json
import os
from pathlib import Path
import time
import traceback
from playwright.sync_api import sync_playwright, expect

URL = os.environ.get('WORKOS_E2E_URL', 'http://127.0.0.1:18766')
OUT = Path(os.environ.get('LOCALAPPDATA', '.')) / 'LocalWorkOS-dev' / 'browser'
CHROME = r'C:\Program Files\Google\Chrome\Application\chrome.exe'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    token = str(int(time.time()))
    project_name = '合成E2E项目-' + token
    edited_name = project_name + '-已编辑'
    task_name = '合成E2E任务-' + token
    note_name = '合成E2E研究结论-' + token
    errors, results, overflows = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(10000)
        page.on('pageerror', lambda error: errors.append('pageerror: ' + str(error)))
        page.on('console', lambda message: errors.append('console: ' + message.text) if message.type == 'error' else None)
        # Fail closed on any non-loopback browser request, including optional models.
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(URL + '/') or route.request.url.startswith(('blob:', 'data:')) else route.abort())

        def state(workspace='personal'):
            response = context.request.get(URL + '/api/state', headers={'X-Workspace': workspace})
            assert response.ok, response.status
            return response.json()

        def nav(route):
            if page.viewport_size['width'] < 700:
                page.locator('#mobile-menu').click()
            page.locator('#sidebar button[data-page="' + route + '"]').click()
            expect(page.locator('#main')).to_have_attribute('aria-busy', 'false')
            page.wait_for_function('(r) => location.hash === "#" + r', arg=route)

        def submit():
            page.locator('#modal-submit').click()
            expect(page.locator('#modal')).not_to_be_visible()
            assert page.locator('.toast.error').count() == 0, page.locator('.toast.error').all_text_contents()

        def new_record(collection):
            page.locator('#main [data-action="create"][data-collection="' + collection + '"]').first.click()
            expect(page.locator('#modal')).to_be_visible()

        def switch(workspace):
            page.locator('#workspace-switch').click()
            page.locator('#workspace-choice').select_option(workspace)
            submit()
            expect(page.locator('#footer-workspace')).to_contain_text('演示' if workspace == 'demo' else '个人')
            expect(page.locator('#main')).to_have_attribute('aria-busy', 'false')

        def run(name, action):
            try:
                action()
                results.append({'name': name, 'status': 'pass'})
            except Exception as exc:
                results.append({'name': name, 'status': 'fail', 'error': str(exc), 'traceback': traceback.format_exc()})
                page.screenshot(path=str(OUT / (name + '-failure.png')), full_page=True)
                # Close transient UI so independent checks can proceed.
                page.keyboard.press('Escape')
                page.keyboard.press('Escape')

        page.goto(URL, wait_until='networkidle')
        expect(page.locator('#main')).to_have_attribute('aria-busy', 'false')
        assert '个人' in page.locator('#footer-workspace').inner_text()

        def project_task():
            nav('projects')
            new_record('projects')
            page.locator('#field-name').fill(project_name)
            page.locator('#field-sector').fill('合成测试行业')
            page.locator('#field-thesis').fill('仅为自动化测试合成数据。')
            submit()
            card = page.locator('.project-card').filter(has_text=project_name)
            expect(card).to_be_visible()
            card.locator('[aria-label="编辑项目"]').click()
            page.locator('#field-name').fill(edited_name)
            page.locator('#field-stage').select_option('尽调')
            submit()
            nav('tasks')
            new_record('tasks')
            page.locator('#field-title').fill(task_name)
            page.locator('#field-project_id').select_option(label=edited_name)
            submit()
            page.locator('.task-card-title').filter(has_text=task_name).click()
            page.locator('#field-description').fill('合成任务说明已编辑')
            submit()
            card = page.locator('.task-card').filter(has_text=task_name)
            card.locator('[data-task-status]').select_option('进行中')
            expect(page.locator('.kanban-column').filter(has=page.locator('.kanban-head', has_text='进行中')).locator('.task-card-title').filter(has_text=task_name)).to_be_visible()
            data = state()
            task = next(t for t in data['tasks'] if t['title'] == task_name)
            assert task['status'] == '进行中' and task['description'] == '合成任务说明已编辑'
        run('project-task-crud', project_task)

        def research():
            nav('research')
            page.locator('#research-project').select_option(label=edited_name)
            text = '合成星河公司收入为100百万元。收入增长来自合成客户订单。所有数字和公司都是合成测试资料。'
            page.locator('#upload-input').set_input_files({'name': '合成E2E证据-' + token + '.txt', 'mimeType': 'text/plain', 'buffer': text.encode('utf-8')})
            expect(page.locator('.source-name').filter(has_text=token)).to_be_visible()
            checkbox = page.locator('.source-row').filter(has_text=token).locator('[data-source-id]')
            checkbox.check()
            page.locator('#question-input').fill('星河公司收入')
            page.locator('#ask-form button[type="submit"]').click()
            expect(page.locator('.citation').first).to_be_visible()
            page.locator('.citation').first.click()
            expect(page.locator('#document-dialog .document-chunk.highlight')).to_contain_text('100百万元')
            page.locator('#document-dialog [aria-label="关闭原文"]').click()
            page.locator('[data-action="answer-note"]').first.click()
            page.locator('#field-title').fill(note_name)
            submit()
            note = page.locator('.note-item').filter(has_text=note_name)
            expect(note).to_be_visible()
            note.locator('[data-action="note-deliverable"]').click()
            expect(page.locator('#field-body')).to_contain_text('100百万元')
            submit()
            nav('deliverables')
            page.locator('[data-action="select-deliverable"]').filter(has_text=note_name).click()
            expect(page.locator('#deliverable-body')).to_contain_text('100百万元')
            for fmt in ('md', 'html'):
                with page.expect_download() as download:
                    page.locator('[data-action="export"][data-format="' + fmt + '"]').click()
                file = OUT / ('synthetic-' + token + '.' + fmt)
                download.value.save_as(str(file))
                exported = file.read_text(encoding='utf-8')
                assert note_name in exported and '100百万元' in exported
            page.screenshot(path=str(OUT / 'workflow-deliverable.png'), full_page=True)
        run('research-citation-deliverable-download', research)

        def meetings():
            nav('meetings')
            new_record('meetings')
            page.locator('#field-title').fill('合成E2E会议-' + token)
            page.locator('#field-project_id').select_option(label=edited_name)
            page.locator('#field-transcript').fill('张三：请在2027-01-15前完成合成收入核实。\n李四：负责整理合成客户订单清单，2027-01-16前提交。')
            submit()
            before = len(state()['tasks'])
            page.locator('[data-action="meeting-draft"]').click()
            expect(page.locator('.action-candidate').first).to_be_visible()
            assert len(state()['tasks']) == before, 'Rules draft must not create tasks automatically'
            checks = page.locator('#meeting-actions-form input[name="confirmed"]')
            assert checks.count() >= 1
            assert all(not checks.nth(i).is_checked() for i in range(checks.count()))
            checks.first.check()
            page.locator('#meeting-actions-form button[type="submit"]').click()
            expect(page.locator('.action-candidate.created')).to_have_count(1)
            assert len(state()['tasks']) == before + 1
            expect(page.locator('#meeting-actions-form input[name="confirmed"]').first).to_be_disabled()
            page.locator('#meeting-actions-form button[type="submit"]').click()
            expect(page.locator('.toast.error').filter(has_text='请先逐项核实')).to_be_visible()
            assert len(state()['tasks']) == before + 1, 'Repeated confirmation must not duplicate a task'
            page.locator('.toast.error button').click()
            page.locator('#meeting-summary').fill('合成会议纪要，行动项已逐条确认。')
            page.locator('#meeting-summary-form button[type="submit"]').click()
            expect(page.locator('#meeting-save-state')).to_contain_text('已保存')
        run('meeting-confirm-action', meetings)

        def finance():
            nav('finance')
            expect(page.locator('.scenario-card.base .scenario-irr')).to_be_visible()
            old = page.locator('.scenario-card.base .scenario-irr').inner_text()
            page.locator('#assumption-growth').fill('10')
            page.locator('#finance-form button[type="submit"]').click()
            expect(page.locator('#finance-form fieldset')).to_be_enabled()
            new = page.locator('.scenario-card.base .scenario-irr').inner_text()
            assert old != new, (old, new)
            assert page.locator('.sensitivity-table tbody tr').count() > 0
        run('finance-assumption-recompute', finance)

        def persistence_search_isolation():
            nav('projects')
            expect(page.locator('.project-title').filter(has_text=edited_name)).to_be_visible()
            page.reload(wait_until='networkidle')
            expect(page.locator('.project-title').filter(has_text=edited_name)).to_be_visible()
            page.keyboard.press('Control+k')
            expect(page.locator('#global-search')).to_be_focused()
            page.locator('#global-search').fill(edited_name)
            expect(page.locator('.search-result[data-collection="projects"]').filter(has_text=edited_name)).to_be_visible()
            page.keyboard.press('Escape')
            expect(page.locator('#search-dialog')).not_to_be_visible()
            switch('demo')
            nav('projects')
            assert page.locator('.project-title').filter(has_text=edited_name).count() == 0
            nav('memory')
            page.locator('[data-action="memory-scan"]').first.click()
            expect(page.locator('.toast').filter(has_text='真实记忆仅能导入个人')).to_be_visible()
            assert not page.locator('#modal').is_visible()
            # Expected warning toast is not a console error; close before later tests.
            page.locator('.toast.error button').click()
            switch('personal')
            nav('projects')
            expect(page.locator('.project-title').filter(has_text=edited_name)).to_be_visible()
            nav('memory')
            expect(page.locator('.memory-card')).to_have_count(0)
            # Do not click scan: the live service could know the actual memory root.
        run('refresh-workspace-search-memory-boundary', persistence_search_isolation)

        def modal_safety():
            nav('tasks')
            disposable = '合成删除取消-' + token
            new_record('tasks')
            page.locator('#field-title').fill(disposable)
            submit()
            page.locator('.task-card-title').filter(has_text=disposable).click()
            page.locator('#modal [data-action="modal-delete"]').click()
            confirm = page.locator('dialog[open]').filter(has=page.locator('.confirm-copy'))
            expect(confirm).to_be_visible()
            confirm.locator('button[value="cancel"]').last.click()
            expect(confirm).not_to_be_visible()
            assert any(t['title'] == disposable for t in state()['tasks'])
            page.locator('.task-card-title').filter(has_text=disposable).click()
            page.locator('#modal [data-action="modal-delete"]').click()
            confirm = page.locator('dialog[open]').filter(has=page.locator('.confirm-copy'))
            expect(confirm).to_be_visible()
            confirm.locator('button[value="confirm"]').click()
            expect(page.locator('.task-card-title').filter(has_text=disposable)).to_have_count(0)
            assert not any(t['title'] == disposable for t in state()['tasks'])
            nav('deliverables')
            page.locator('[data-action="select-deliverable"]').filter(has_text=note_name).click()
            old = page.locator('#deliverable-body').input_value()
            page.locator('#deliverable-body').fill(old + '\n合成尚未保存修改')
            page.locator('#sidebar button[data-page="projects"]').click()
            confirm = page.locator('dialog[open]').filter(has=page.locator('.confirm-copy'))
            expect(confirm).to_be_visible()
            confirm.locator('button[value="cancel"]').last.click()
            expect(page.locator('#deliverable-body')).to_have_value(old + '\n合成尚未保存修改')
            assert page.url.endswith('#deliverables')
            assert next(d for d in state()['deliverables'] if d['title'] == note_name)['body'] == old
            page.locator('#deliverable-form button[type="submit"]').click()
            expect(page.locator('#deliverable-save-state')).to_contain_text('已保存')
        run('modal-delete-and-unsaved-cancel', modal_safety)

        def mobile():
            page.set_viewport_size({'width': 390, 'height': 844})
            for route in ('overview', 'projects', 'research', 'meetings', 'tasks', 'memory', 'finance', 'deliverables', 'settings'):
                nav(route)
                expect(page.locator('#sidebar')).not_to_be_visible()
                # Let the off-canvas navigation transition settle before measuring roots.
                page.wait_for_timeout(400)
                metrics = page.evaluate('({width:innerWidth, html:document.documentElement.scrollWidth, body:document.body.scrollWidth})')
                if max(metrics['html'], metrics['body']) > metrics['width'] + 1:
                    overflows.append({'route': route, **metrics})
                    page.screenshot(path=str(OUT / ('mobile-' + route + '-overflow.png')), full_page=True)
            for _ in range(20):
                page.keyboard.press('Tab')
                assert not page.evaluate('Boolean(document.activeElement.closest("#sidebar"))'), 'Collapsed sidebar must be excluded from keyboard focus'
            page.screenshot(path=str(OUT / 'mobile-settings.png'), full_page=True, animations='disabled')
            assert not overflows, overflows
        run('mobile-all-routes-overflow', mobile)
        results.append({'name': 'browser-console', 'status': 'fail' if errors else 'pass', 'errors': errors})
        report = {'url': URL, 'synthetic_token': token, 'results': results, 'overflows': overflows}
        (OUT / 'workflow-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()
        return 1 if any(r['status'] == 'fail' for r in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
