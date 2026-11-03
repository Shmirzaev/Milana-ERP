"""Private VM107 UI QA for the real simulator backend. Authoring only; owner runs it.

A failed or interrupted enrollment is HOLD: do not replay, clean the lane, or
rerun against these fixtures until DB and journal state have been reviewed.
"""
from pathlib import Path
import asyncio
import base64
import json
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path.home() / 'development-services/visual-testing/.venv/lib/python3.12/site-packages'))
from playwright.async_api import async_playwright
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RT = Path('/home/ismoil/workspaces/turnstile-backend-runtime-20261103')
OUT = RT / 'evidence'
BASE = 'http://127.0.0.1:13109'
PORT = 13109
LABELS = {'en': ('Turnstile access', 'Close', 'Simulator accepted all targets'),
          'ru': ('Доступ через турникет', 'Закрыть', 'Симулятор принял все устройства'),
          'uz': ('Turniketga kirish', 'Yopish', 'Simulyator barcha qurilmalarni qabul qildi')}


def db_snapshot():
    code = '''from sqlalchemy import text
from app.db.session import engine
import json
with engine.connect() as c:
 c.execute(text("SET TRANSACTION READ ONLY"))
 result={}
 for table,where in [("employees"," WHERE id <= 4"),("attendance_devices"," WHERE id <= 4"),("attendance_people",""),("attendance_events","")]:
  result[table]=dict(c.execute(text("SELECT count(*) AS count,md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text,'[]')) AS fingerprint FROM "+table+" t"+where)).mappings().one())
 result['device_names']=[row[0] for row in c.execute(text("SELECT name FROM attendance_devices WHERE device_key IN ('preview-lane-1','preview-lane-2','preview-lane-3','preview-lane-4') ORDER BY id"))]
 rows=c.execute(text("SELECT o.id,o.external_person_id,o.full_name,o.mode,t.state,t.device_id,p.write_count FROM gate_operations o JOIN gate_targets t ON t.operation_id=o.id LEFT JOIN gate_simulator_people p ON p.binding_id=t.binding_id WHERE o.employee_id=(SELECT id FROM employees WHERE employee_no='920001' AND factory_code='MIL') ORDER BY o.id,t.device_id")).mappings().all()
 result['enrollment']=[dict(row) for row in rows]
 print(json.dumps(result))
'''
    p = subprocess.run([str(RT / 'dev'), 'exec', '-T', 'backend', 'python', '-c', code], capture_output=True, text=True, timeout=35)
    if p.returncode:
        raise RuntimeError('Development DB readback failed; inspect owned runtime without exposing environment')
    return json.loads(p.stdout)


async def main():
    OUT.mkdir(exist_ok=True)
    report = {'status': 'RUNNING', 'checks': [], 'omissions': ['lost response fault injection not run']}
    errors, failures, blocked, enroll_responses, photo_responses = [], [], [], [], []
    accepted_receipt = False
    async def call(session, name, args):
        result = await asyncio.wait_for(session.call_tool(name, args), 115)
        if result.is_error:
            raise RuntimeError(name + ': ' + ' '.join(getattr(c, 'text', '') for c in result.content)[:500])
        return result
    def text(result):
        return '\n'.join(getattr(c, 'text', '') for c in result.content)
    try:
        report['baseline'] = await asyncio.to_thread(db_snapshot)
        original = json.loads((OUT / 'original-controls.json').read_text())
        assert {key: report['baseline'][key] for key in original} == original, 'Original controls do not match baseline'
        assert not report['baseline']['enrollment'], 'HOLD: employee already has an operation; do not replay'
        params = StdioServerParameters(command=str(Path.home() / '.local/share/milana-tools/venv/bin/python'), args=[str(Path.home() / 'development-services/agent-qa-20261103/visual_agent_mcp.py')])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                state = json.loads(text(await call(session, 'qa_start', {})))
                report['lane'] = state['name']
                for component in ('devtools', 'desktop'):
                    catalog = await call(session, 'qa_tool_catalog', {'component': component})
                    assert 'tools' in text(catalog)
                opened = await call(session, 'qa_browser', {'tool': 'new_page', 'arguments': {'url': BASE + '/login?qa_lane=' + state['name']}})
                match = re.search(r'(?m)^(\d+): .*\[selected\]', text(opened))
                assert match, 'Could not bind the owned QA page'
                pageid = int(match.group(1))
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.connect_over_cdp(state['cdp_url'])
                    context = browser.contexts[0]
                    pages = [page for page in context.pages if 'qa_lane=' + state['name'] in page.url]
                    assert len(pages) == 1, 'Owned page binding is ambiguous'
                    page = pages[0]
                    cdp = await context.new_cdp_session(page)
                    async def guard(route):
                        u = urlsplit(route.request.url)
                        if u.scheme in ('data', 'blob') or (u.scheme == 'http' and u.hostname == '127.0.0.1' and u.port == PORT):
                            await route.continue_()
                        else:
                            blocked.append(u.scheme + '://' + str(u.hostname))
                            await route.abort('blockedbyclient')
                    await context.route('**/*', guard)
                    page.on('pageerror', lambda e: errors.append(str(e)[:400]))
                    page.on('console', lambda message: errors.append(message.text[:400]) if message.type == 'error' and '409' not in message.text else None)
                    def response_seen(response):
                        path = urlsplit(response.url).path
                        if response.request.method == 'POST' and path.endswith('/enroll'):
                            enroll_responses.append({'path': path, 'status': response.status})
                        if response.request.method == 'POST' and path.endswith('/photos'):
                            photo_responses.append({'path': path, 'status': response.status})
                        if response.status >= 400:
                            failures.append({'path': path, 'status': response.status})
                    page.on('response', response_seen)
                    await page.goto(BASE + '/login', timeout=90000)
                    credentials = json.loads((RT / 'private/qa-login.json').read_text())
                    await page.locator('input[type=email]').fill(credentials['email'])
                    await page.locator('input[type=password]').fill(credentials['password'])
                    await page.locator('button[type=submit]').click()
                    await page.wait_for_url(lambda u: '/login' not in str(u), timeout=60000)
                    await page.evaluate('localStorage.setItem("erp_lang","en")')
                    await page.goto(BASE + '/hr/employees', timeout=90000)
                    async def open_employee(number, lang='en'):
                        row = page.get_by_role('row').filter(has_text=number)
                        await row.wait_for(timeout=30000)
                        assert await row.count() == 1, 'Employee row must be unique'
                        await row.get_by_role('button', name=LABELS[lang][0], exact=True).click()
                        gate = page.get_by_test_id('gate-preview')
                        await gate.wait_for()
                        await gate.get_by_text(number, exact=True).first.wait_for()
                        return gate
                    async def browser_shot(name, employee='920001'):
                        await page.bring_to_front()
                        snapshot = await call(session, 'qa_browser', {'tool': 'take_snapshot', 'arguments': {'pageId': pageid}})
                        assert employee in text(snapshot), 'Screenshot belongs to a different employee'
                        result = await call(session, 'qa_browser', {'tool': 'take_screenshot', 'arguments': {'pageId': pageid, 'format': 'png'}})
                        images = [c for c in result.content if c.type == 'image']
                        assert images, 'Browser screenshot missing'
                        data = base64.b64decode(images[0].data)
                        assert len(data) > 15000, 'Blank screenshot refused'
                        (OUT / name).write_bytes(data)
                    async def native_shot(name):
                        await page.bring_to_front()
                        result = await call(session, 'qa_desktop', {'tool': 'screenshot', 'arguments': {'pid': state['chrome_pid'], 'max_width': 1600, 'max_height': 1200}})
                        images = [c for c in result.content if c.type == 'image']
                        assert images, 'Native screenshot missing'
                        (OUT / name).write_bytes(base64.b64decode(images[0].data))
                    gate = await open_employee('920001')
                    for label in ('Edit details', 'Replace photo', 'Revoke access'):
                        assert await gate.get_by_role('button', name=label, exact=True).is_disabled()
                    names = report['baseline']['device_names']
                    assert len(names) == len(set(names)) == 4
                    for label in names:
                        await gate.get_by_text(label, exact=True).wait_for()
                    portrait = await page.evaluate('''()=>{const c=document.createElement('canvas');c.width=480;c.height=640;const x=c.getContext('2d');x.fillStyle='#dfe7d5';x.fillRect(0,0,480,640);x.fillStyle='#778b65';x.beginPath();x.arc(240,236,90,0,Math.PI*2);x.fill();x.beginPath();x.ellipse(240,575,165,190,0,0,Math.PI*2);x.fill();return c.toDataURL('image/png').split(',')[1]}''')
                    picture = base64.b64decode(portrait)
                    async def prepare(g):
                        await g.locator('input[type=file]').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':picture})
                        await g.locator('img').wait_for()
                        await g.get_by_label('Face is straight and fully visible', exact=True).check()
                        await g.get_by_label('Eyes are open; the picture is clear', exact=True).check()
                        await g.get_by_role('button', name='Select all', exact=True).click()
                        await g.get_by_role('button', name='Review change', exact=True).click()
                        await g.get_by_role('region', name='Confirm selected change').wait_for()
                    await prepare(gate)
                    await call(session, 'qa_browser', {'tool':'emulate', 'arguments':{'pageId':pageid,'viewport':'1280x800x1'}})
                    await native_shot('backend-desktop-review-native.png')
                    await browser_shot('backend-desktop-review.png')
                    # No retry if this click has an unknown outcome. The report remains HOLD.
                    report['status'] = 'HOLD'; report['pending_step'] = 'enrollment submitted; verify receipt and DB before replay'
                    await gate.get_by_role('button', name='Apply to turnstiles', exact=True).click()
                    await gate.get_by_role('button', name='Process or reconcile in simulator', exact=True).wait_for(timeout=60000)
                    assert len(photo_responses) == 1 and photo_responses[0]['status'] in (200, 201)
                    assert len(enroll_responses) == 1 and enroll_responses[0]['status'] == 202
                    accepted_receipt = True
                    assert await gate.locator('[data-gate-result]').get_by_text('Queued', exact=True).count() == 4
                    report['checks'].append('actual photo upload and one enrollment produced four queued targets')
                    await gate.get_by_role('button', name='Process or reconcile in simulator', exact=True).click()
                    result = gate.locator('[data-gate-result]')
                    await result.get_by_role('button', name='Simulate device reconnect', exact=True).wait_for(timeout=60000)
                    assert await result.get_by_text('Accepted by simulator', exact=True).count() == 3
                    assert await result.get_by_text('Waiting for device', exact=True).count() == 1
                    await browser_shot('backend-desktop-partial.png')
                    await native_shot('backend-desktop-partial-native.png')
                    await result.get_by_role('button', name='Simulate device reconnect', exact=True).click()
                    await result.get_by_text('Simulator accepted all targets', exact=True).wait_for(timeout=60000)
                    assert await result.get_by_text('Accepted by simulator', exact=True).count() == 4
                    await browser_shot('backend-desktop-result.png')
                    await native_shot('backend-desktop-result-native.png')
                    await gate.get_by_role('button', name='Close', exact=True).click()
                    gate = await open_employee('920001')
                    await gate.get_by_text('Simulator accepted all targets', exact=True).wait_for()
                    await gate.get_by_role('button', name='Close', exact=True).click()
                    await page.reload(timeout=90000)
                    gate = await open_employee('920001')
                    await gate.get_by_text('Simulator accepted all targets', exact=True).wait_for()
                    for label in names:
                        await gate.locator('[data-gate-result]').get_by_text(label, exact=True).wait_for()
                    report['checks'].append('reconnect, reopen and reload read back all four simulator results')
                    await gate.get_by_role('button', name='Close', exact=True).click()
                    # A known existing identity receives a definite refusal; inputs remain reviewable.
                    old = await open_employee('910001')
                    await prepare(old)
                    await old.get_by_role('button', name='Apply to turnstiles', exact=True).click()
                    await old.get_by_text('The server refused this request. Check your selection and try again.', exact=True).wait_for(timeout=60000)
                    assert enroll_responses[-1]['status'] == 409
                    assert await old.locator('img').count() > 0
                    assert await old.get_by_label('Face is straight and fully visible', exact=True).is_checked()
                    assert await old.get_by_label('Eyes are open; the picture is clear', exact=True).is_checked()
                    assert await old.get_by_role('button', name='Review change', exact=True).is_enabled()
                    assert await old.locator('[data-gate-result]').count() == 0
                    await old.get_by_role('button', name='Close', exact=True).click()
                    report['checks'].append('definite 409 preserves inputs and does not create false history')
                    for lang in ('en', 'ru', 'uz'):
                        await page.evaluate('(lang)=>localStorage.setItem("erp_lang",lang)', lang)
                        await page.reload(timeout=90000)
                        await call(session, 'qa_browser', {'tool':'emulate','arguments':{'pageId':pageid,'viewport':'390x844x1,mobile,touch'}})
                        await cdp.send('Emulation.setDeviceMetricsOverride', {'width':390,'height':844,'screenWidth':390,'screenHeight':844,'deviceScaleFactor':1,'mobile':True})
                        await cdp.send('Emulation.setTouchEmulationEnabled', {'enabled':True,'maxTouchPoints':1})
                        await page.wait_for_function('screen.width===390 && innerWidth===390', timeout=20000)
                        gate = await open_employee('920001', lang)
                        await gate.get_by_text(LABELS[lang][2], exact=True).wait_for()
                        metrics = await page.evaluate('({screen:screen.width,inner:innerWidth,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})')
                        bounds = await gate.bounding_box()
                        assert metrics['screen'] == metrics['inner'] == 390 and bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
                        await browser_shot('backend-mobile-' + lang + '-form.png')
                        await gate.locator('[data-gate-result]').scroll_into_view_if_needed()
                        await browser_shot('backend-mobile-' + lang + '-result.png')
                        report['checks'].append({'locale':lang, 'metrics':metrics, 'panel':bounds})
                        await gate.get_by_role('button', name=LABELS[lang][1], exact=True).click()
                    report['db_after'] = await asyncio.to_thread(db_snapshot)
                    assert {key: report['db_after'][key] for key in original} == original, 'Original attendance or employee data changed'
                    rows = report['db_after']['enrollment']
                    assert len(rows) == 4 and len({row['id'] for row in rows}) == 1
                    assert all(row['external_person_id'] == '920001' and row['mode'] == 'simulator' and row['state'] == 'succeeded' and row['write_count'] == 1 for row in rows)
                    assert len({row['device_id'] for row in rows}) == 4
                    unexpected = [item for item in failures if not (item['status'] == 409 and item['path'].endswith('/enroll'))]
                    assert len(failures) == 1 and not unexpected, failures
                    assert not errors and not blocked, (errors, blocked)
                    report.update(page_errors=errors, http_failures=failures, external_requests=blocked, enrollment_responses=enroll_responses)
                    await call(session, 'qa_browser', {'tool':'list_console_messages','arguments':{'pageId':pageid,'types':['error','warn']}})
                    await call(session, 'qa_browser', {'tool':'list_network_requests','arguments':{'pageId':pageid,'pageSize':20}})
                await call(session, 'qa_stop', {})
                report['owned_lane_cleanup'] = True
        report.pop('pending_step', None)
        report['status'] = 'PASSED'
    except BaseException as exc:
        report.update(status='HOLD', error=repr(exc), accepted_receipt=accepted_receipt,
                      page_errors=errors, http_failures=failures, external_requests=blocked,
                      enrollment_responses=enroll_responses)
        raise
    finally:
        data = json.dumps(report, indent=2, ensure_ascii=False)
        (OUT / ('backend-report-' + str(time.time_ns()) + '.json')).write_text(data)
        (OUT / 'backend-report-latest.json').write_text(data)
        print(data, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
