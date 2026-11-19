"""Owner-run synthetic lost-response and terminal-readback challenge on VM107.

Never rerun after uncertain completion. Preserve lane and inspect the journal,
receipt and database if any stage fails; only stop the owned lane after success.
"""
from pathlib import Path
import asyncio, base64, json, re, subprocess, sys, time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path.home() / 'development-services/visual-testing/.venv/lib/python3.12/site-packages'))
from playwright.async_api import async_playwright
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RT = Path('/home/ismoil/workspaces/turnstile-backend-runtime-20261103')
OUT = RT / 'evidence'
BASE = 'http://127.0.0.1:13109'


def db_inspect():
    code = '''from sqlalchemy import text
from app.db.session import engine
import json
with engine.connect() as c:
 c.execute(text("SET TRANSACTION READ ONLY"))
 result={}
 for table,where in [("employees"," WHERE id <= 4"),("attendance_devices"," WHERE id <= 4"),("attendance_people",""),("attendance_events","")]:
  result[table]=dict(c.execute(text("SELECT count(*) AS count,md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text,'[]')) AS fingerprint FROM "+table+" t"+where)).mappings().one())
 result['employee_id']=c.execute(text("SELECT id FROM employees WHERE employee_no='920002' AND factory_code='MIL'")).scalar_one()
 result['devices']=[dict(r) for r in c.execute(text("SELECT d.id,d.name,s.online,s.mode FROM attendance_devices d JOIN gate_simulator_devices s ON s.device_id=d.id WHERE d.device_key IN ('preview-lane-1','preview-lane-2','preview-lane-3','preview-lane-4') ORDER BY d.id")).mappings()]
 result['rows']=[dict(r) for r in c.execute(text("SELECT o.id,o.external_person_id,o.mode,t.id AS target_id,t.device_id,t.state,t.attempts,p.write_count FROM gate_operations o JOIN gate_targets t ON t.operation_id=o.id LEFT JOIN gate_simulator_people p ON p.binding_id=t.binding_id WHERE o.employee_id=:employee_id ORDER BY o.id,t.device_id"),{'employee_id':result['employee_id']}).mappings()]
 print(json.dumps(result))
'''
    process = subprocess.run([str(RT / 'dev'), 'exec', '-T', 'backend', 'python', '-c', code], capture_output=True, text=True, timeout=35)
    if process.returncode:
        raise RuntimeError('Owned development DB readback failed')
    return json.loads(process.stdout)


def challenge_uncertain(operation_id, employee_id):
    code = '''import json,sys
from sqlalchemy import select
from app.db.session import SessionLocal
from app.libs.enums.turnstile import GateMode,GateTargetState,GateErrorCode
from app.schemas.people.turnstile import GateOperation,GateTarget,GateSimulatorPerson
from app.schemas.people.turnstile_persistence import transition_target
operation_id=int(sys.argv[1]); employee_id=int(sys.argv[2])
with SessionLocal() as db:
 op=db.scalar(select(GateOperation).where(GateOperation.id==operation_id,GateOperation.employee_id==employee_id,GateOperation.external_person_id=='920002',GateOperation.mode==GateMode.SIMULATOR))
 assert op
 targets=db.scalars(select(GateTarget).where(GateTarget.operation_id==op.id).order_by(GateTarget.device_id).with_for_update()).all()
 assert len(targets)==4 and all(t.state==GateTargetState.SUCCEEDED for t in targets)
 t=targets[0]
 person=db.scalar(select(GateSimulatorPerson).where(GateSimulatorPerson.binding_id==t.binding_id))
 assert person and person.write_count==1
 transition_target(db,t,state=GateTargetState.UNCERTAIN,attempts=t.attempts,error_code=GateErrorCode.SIMULATOR_ERROR,lease_token=None,lease_expires_at=None,observed_evidence=None)
 db.commit()
 print(json.dumps({'operation_id':op.id,'target_id':t.id,'prior_write_count':person.write_count}))
'''
    process = subprocess.run([str(RT / 'dev'), 'exec', '-T', 'backend', 'python', '-c', code, str(operation_id), str(employee_id)], capture_output=True, text=True, timeout=35)
    if process.returncode:
        raise RuntimeError('Synthetic target challenge failed; HOLD and inspect this exact fixture')
    return json.loads(process.stdout)


async def main():
    OUT.mkdir(exist_ok=True)
    report = {'status':'HOLD', 'checks':[], 'controlled_fault':None}
    errors, http_errors, request_failures, blocked = [], [], [], []
    requests = []
    receipt = None
    async def call(session, name, args):
        result = await asyncio.wait_for(session.call_tool(name, args), 115)
        if result.is_error:
            raise RuntimeError(name + ': ' + ' '.join(getattr(c, 'text', '') for c in result.content)[:500])
        return result
    def text(result):
        return '\n'.join(getattr(c, 'text', '') for c in result.content)
    try:
        baseline = await asyncio.to_thread(db_inspect)
        original = json.loads((OUT / 'original-controls.json').read_text())
        assert {key:baseline[key] for key in original} == original, 'Original controls differ'
        assert not baseline['rows'], 'HOLD: synthetic 920002 already has an operation'
        assert len(baseline['devices']) == 4 and all(d['online'] and d['mode'] == 'simulator' for d in baseline['devices'])
        employee_id = baseline['employee_id']
        enroll_path = f'/api/turnstile-access/employees/{employee_id}/enroll'
        report['employee_id'] = employee_id
        params = StdioServerParameters(command=str(Path.home() / '.local/share/milana-tools/venv/bin/python'), args=[str(Path.home() / 'development-services/agent-qa-20261103/visual_agent_mcp.py')])
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as session:
                await session.initialize()
                lane = json.loads(text(await call(session, 'qa_start', {})))
                report['lane'] = lane['name']
                for component in ('desktop','devtools'):
                    assert 'tools' in text(await call(session, 'qa_tool_catalog', {'component':component}))
                opened = await call(session, 'qa_browser', {'tool':'new_page','arguments':{'url':BASE + '/login?qa_lane=' + lane['name']}})
                match = re.search(r'(?m)^(\d+): .*\[selected\]', text(opened)); assert match
                pageid = int(match.group(1))
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.connect_over_cdp(lane['cdp_url'])
                    context = browser.contexts[0]
                    pages = [p for p in context.pages if 'qa_lane=' + lane['name'] in p.url]
                    assert len(pages) == 1, 'Owned page binding ambiguous'
                    page = pages[0]
                    async def guard(route):
                        nonlocal receipt
                        request = route.request
                        url = urlsplit(request.url)
                        if not (url.scheme in ('data','blob') or (url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port == 13109)):
                            blocked.append(url.scheme + '://' + str(url.hostname)); await route.abort('blockedbyclient'); return
                        if request.method == 'POST' and url.path == enroll_path:
                            requests.append({'path':url.path,'method':request.method})
                            if len(requests) != 1:
                                await route.abort('blockedbyclient'); return
                            try:
                                response = await route.fetch(timeout=90000)
                                if response.status != 202:
                                    report['controlled_fault'] = {'receipt_status':response.status, 'dropped':False}
                                    await route.fulfill(response=response)
                                    return
                                data = await response.json()
                                assert isinstance(data.get('id'), int) and data.get('external_person_id') == '920002'
                                receipt = {'status':response.status, 'operation_id':data['id']}
                                report['controlled_fault'] = {'receipt_status':202,'operation_id':data['id'],'dropped':True}
                                await route.abort('failed')
                            except Exception as exc:
                                report['controlled_fault'] = {'receipt':receipt,'error':repr(exc),'dropped':False}
                                try: await route.abort('failed')
                                except Exception: pass
                            return
                        await route.continue_()
                    await context.route('**/*', guard)
                    page.on('pageerror', lambda e: errors.append(str(e)[:400]))
                    def console_message(message):
                        if message.type != 'error':
                            return
                        location = urlsplit(message.location.get('url', '')).path
                        controlled = (location == enroll_path and 'net::ERR_FAILED' in message.text
                                      and (report.get('controlled_fault') or {}).get('dropped'))
                        if not controlled:
                            errors.append(message.text[:400])
                    page.on('console', console_message)
                    page.on('response', lambda r: http_errors.append({'path':urlsplit(r.url).path,'status':r.status}) if r.status >= 400 else None)
                    def request_failed(request):
                        path = urlsplit(request.url).path
                        if request.method == 'POST' and path == enroll_path and (report.get('controlled_fault') or {}).get('dropped'):
                            report['controlled_abort_observed'] = True
                        else:
                            request_failures.append({'path':path,'failure':request.failure})
                    page.on('requestfailed', request_failed)
                    await page.goto(BASE+'/login', timeout=90000)
                    credentials = json.loads((RT/'private/qa-login.json').read_text())
                    await page.locator('input[type=email]').fill(credentials['email']); await page.locator('input[type=password]').fill(credentials['password'])
                    await page.locator('button[type=submit]').click(); await page.wait_for_url(lambda u:'/login' not in str(u), timeout=60000)
                    await page.evaluate('localStorage.setItem("erp_lang","en")')
                    await page.goto(BASE+'/hr/employees', timeout=90000)
                    async def open_employee():
                        row = page.get_by_role('row').filter(has_text='920002')
                        await row.wait_for(timeout=30000); assert await row.count() == 1
                        await row.get_by_role('button',name='Turnstile access',exact=True).click()
                        gate = page.get_by_test_id('gate-preview'); await gate.wait_for()
                        await gate.get_by_text('920002',exact=True).first.wait_for()
                        return gate
                    async def shot(name, native=False):
                        await page.bring_to_front()
                        snap=await call(session,'qa_browser',{'tool':'take_snapshot','arguments':{'pageId':pageid}})
                        assert '920002' in text(snap), 'Screenshot target mismatch'
                        if native:
                            result=await call(session,'qa_desktop',{'tool':'screenshot','arguments':{'pid':lane['chrome_pid'],'max_width':1600,'max_height':1200}})
                        else:
                            result=await call(session,'qa_browser',{'tool':'take_screenshot','arguments':{'pageId':pageid,'format':'png'}})
                        images=[c for c in result.content if c.type=='image']; assert images
                        data=base64.b64decode(images[0].data); assert len(data)>15000
                        (OUT/name).write_bytes(data)
                    await call(session,'qa_browser',{'tool':'emulate','arguments':{'pageId':pageid,'viewport':'1270x800x1'}})
                    gate = await open_employee()
                    portrait=await page.evaluate('''()=>{const c=document.createElement('canvas');c.width=480;c.height=640;const x=c.getContext('2d');x.fillStyle='#dfe7d5';x.fillRect(0,0,480,640);x.fillStyle='#778b65';x.beginPath();x.arc(240,236,90,0,Math.PI*2);x.fill();x.beginPath();x.ellipse(240,575,165,190,0,0,Math.PI*2);x.fill();return c.toDataURL('image/png').split(',')[1]}''')
                    await gate.locator('input[type=file]').set_input_files({'name':'synthetic-recovery.png','mimeType':'image/png','buffer':base64.b64decode(portrait)})
                    await gate.locator('img').wait_for()
                    await gate.get_by_label('Face is straight and fully visible',exact=True).check()
                    await gate.get_by_label('Eyes are open; the picture is clear',exact=True).check()
                    await gate.get_by_role('button',name='Select all',exact=True).click()
                    await gate.get_by_role('button',name='Review change',exact=True).click()
                    await gate.get_by_role('region',name='Confirm selected change').wait_for()
                    await gate.get_by_role('button',name='Apply to turnstiles',exact=True).click()
                    await gate.get_by_text('The result is unknown. Recheck or retry the same request; do not submit a new one.',exact=True).wait_for(timeout=90000)
                    assert receipt and receipt['status']==202 and report.get('controlled_abort_observed')
                    assert len(requests)==1
                    journal = await page.evaluate('''employee=>Object.entries(sessionStorage).filter(([k])=>k.startsWith('turnstile-submit:v1:') && k.endsWith(':'+employee)).map(([k,v])=>({key:k,value:JSON.parse(v)}))''', str(employee_id))
                    assert len(journal)==1 and journal[0]['value']['payload']['expected_employee_no']=='920002'
                    journal_key=journal[0]['key']; journal_token=journal[0]['value']['key']
                    assert await gate.get_by_role('button',name='Apply to turnstiles',exact=True).is_disabled()
                    await shot('backend-recovery-unknown.png'); await shot('backend-recovery-unknown-native.png',native=True)
                    await gate.get_by_role('button',name='Close',exact=True).click()
                    await page.reload(timeout=90000)
                    gate = await open_employee()
                    await gate.get_by_text('The result is unknown. Recheck or retry the same request; do not submit a new one.',exact=True).wait_for()
                    assert await page.evaluate('(key)=>sessionStorage.getItem(key)!==null',journal_key)
                    assert await gate.get_by_role('button',name='Review change',exact=True).is_disabled()
                    await shot('backend-recovery-reopened.png')
                    await gate.get_by_role('button',name='Recheck server',exact=True).first.click()
                    await gate.get_by_role('button',name='Process or reconcile in simulator',exact=True).wait_for(timeout=60000)
                    await page.wait_for_function('(key)=>sessionStorage.getItem(key)===null',arg=journal_key, timeout=30000)
                    assert await page.evaluate('(key)=>sessionStorage.getItem(key)===null',journal_key)
                    assert len(requests)==1 and await gate.locator('[data-gate-result]').get_by_text('Queued',exact=True).count()==4
                    report['checks'].append('accepted response dropped; reopened journal reconciled without another enrollment POST')
                    await gate.get_by_role('button',name='Process or reconcile in simulator',exact=True).click()
                    await gate.get_by_text('Simulator accepted all targets',exact=True).wait_for(timeout=60000)
                    before = await asyncio.to_thread(db_inspect)
                    rows=before['rows']
                    assert len(rows)==4 and {r['id'] for r in rows}=={receipt['operation_id']}
                    assert all(r['state']=='succeeded' and r['write_count']==1 for r in rows)
                    report['challenge'] = await asyncio.to_thread(challenge_uncertain, receipt['operation_id'], employee_id)
                    await gate.locator('[data-gate-result]').get_by_role('button',name='Recheck server',exact=True).click()
                    await gate.locator('[data-gate-result]').get_by_text('Uncertain',exact=True).wait_for(timeout=60000)
                    await gate.get_by_role('button',name='Process or reconcile in simulator',exact=True).click()
                    await gate.get_by_text('Simulator accepted all targets',exact=True).wait_for(timeout=60000)
                    after = await asyncio.to_thread(db_inspect)
                    assert len(after['rows'])==4 and {r['id'] for r in after['rows']}=={receipt['operation_id']}
                    assert all(r['state']=='succeeded' and r['write_count']==1 for r in after['rows'])
                    assert {key:after[key] for key in original} == original
                    assert len(requests)==1 and not errors and not http_errors and not request_failures and not blocked
                    await shot('backend-recovery-reconciled.png'); await shot('backend-recovery-reconciled-native.png',native=True)
                    report['checks'].append('uncertain accepted target reconciled by readback without another write')
                    report.update(receipt=receipt,enrollment_posts=len(requests),db_after=after,console_errors=errors,http_errors=http_errors,request_failures=request_failures,blocked_requests=blocked)
                    await call(session,'qa_browser',{'tool':'list_console_messages','arguments':{'pageId':pageid,'types':['error','warn']}})
                    await call(session,'qa_browser',{'tool':'list_network_requests','arguments':{'pageId':pageid,'pageSize':30}})
                await call(session,'qa_stop',{})
                report['owned_lane_cleanup']=True
        report['status']='PASSED'
    except BaseException as exc:
        report.update(status='HOLD',error=repr(exc),receipt=receipt,enrollment_posts=len(requests),console_errors=errors,http_errors=http_errors,request_failures=request_failures,blocked_requests=blocked)
        raise
    finally:
        data=json.dumps(report,indent=2,ensure_ascii=False)
        (OUT/('backend-recovery-report-'+str(time.time_ns())+'.json')).write_text(data)
        (OUT/'backend-recovery-report-latest.json').write_text(data)
        print(data,flush=True)


if __name__=='__main__':
    asyncio.run(main())
