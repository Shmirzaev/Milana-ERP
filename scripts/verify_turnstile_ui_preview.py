from pathlib import Path
import asyncio, base64, hashlib, json, re, subprocess, sys, time
sys.path.insert(0, str(Path.home()/'development-services/visual-testing/.venv/lib/python3.12/site-packages'))
from playwright.async_api import async_playwright
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

RT=Path('/home/ismoil/workspaces/turnstile-ui-runtime-20261103')
OUT=RT/'evidence'; OUT.mkdir(exist_ok=True)
BASE='http://127.0.0.1:13079'
def db_snapshot():
    code='''from sqlalchemy import text
from app.db.session import engine
import json
with engine.connect() as c:
 c.execute(text("SET TRANSACTION READ ONLY"))
 result={}
 for table in ["employees","attendance_devices","attendance_people","attendance_events"]:
  result[table]=dict(c.execute(text("SELECT count(*) AS count,md5(coalesce(jsonb_agg(to_jsonb(t) ORDER BY id)::text,'[]')) AS fingerprint FROM "+table+" t")).mappings().one())
 print(json.dumps(result))
'''
    r=subprocess.run([str(RT/'dev'),'exec','-T','backend','python','-c',code],capture_output=True,text=True,timeout=35)
    if r.returncode: raise RuntimeError('Development DB readback failed')
    return json.loads(r.stdout)

async def main():
    report={'status':'RUNNING','checks':[]}; console=[]; failed=[]; blocked=[]
    async def call(s,name,args):
        result=await asyncio.wait_for(s.call_tool(name,args),115)
        if result.is_error: raise RuntimeError(name+': '+' '.join(getattr(c,'text','') for c in result.content)[:500])
        return result
    def text(result): return '\n'.join(getattr(c,'text','') for c in result.content)
    try:
        params=StdioServerParameters(command=str(Path.home()/'.local/share/milana-tools/venv/bin/python'),args=[str(Path.home()/'development-services/agent-qa-20261103/visual_agent_mcp.py')])
        async with stdio_client(params) as (r,w):
            async with ClientSession(r,w) as s:
                await s.initialize()
                state=json.loads(text(await call(s,'qa_start',{}))); report['lane']=state['name']
                for component in ['devtools','desktop']:
                    catalog=await call(s,'qa_tool_catalog',{'component':component}); (OUT/(component+'-catalog.json')).write_text(text(catalog)); assert 'tools' in text(catalog)
                owned_url=BASE+'/login?qa_lane='+state['name']
                opened=await call(s,'qa_browser',{'tool':'new_page','arguments':{'url':owned_url}})
                match=re.search(r'(?m)^(\d+): .*\[selected\]',text(opened)); assert match,text(opened); pageid=int(match.group(1))
                async with async_playwright() as p:
                    browser=await p.chromium.connect_over_cdp(state['cdp_url']); context=browser.contexts[0]
                    matches=[pg for pg in context.pages if 'qa_lane='+state['name'] in pg.url]; assert len(matches)==1,'Owned page binding is ambiguous'
                    page=matches[0]; await page.bring_to_front()
                    device_session=await context.new_cdp_session(page)
                    async def guard(route):
                        from urllib.parse import urlsplit
                        u=urlsplit(route.request.url)
                        if u.scheme in ['blob','data'] or (u.scheme=='http' and u.hostname=='127.0.0.1' and u.port==13079): await route.continue_()
                        else: blocked.append(u.scheme+'://'+str(u.hostname)); await route.abort('blockedbyclient')
                    await context.route('**/*',guard)
                    page.on('pageerror',lambda e:console.append(str(e)[:400]))
                    page.on('response',lambda r:failed.append({'path':r.url.split('13079')[-1].split('?')[0],'status':r.status}) if r.status>=400 else None)
                    await page.goto(BASE+'/login',timeout=90000)
                    credential=json.loads((RT/'private/qa-login.json').read_text())
                    await page.locator('input[type=email]').fill(credential['email']); await page.locator('input[type=password]').fill(credential['password'])
                    await page.locator('button[type=submit]').click(); await page.wait_for_url(lambda u:'/login' not in str(u),timeout=60000)
                    await page.evaluate('localStorage.setItem("erp_lang","en")')
                    await page.goto(BASE+'/hr/employees',timeout=90000); await page.get_by_role('button',name='Open preview',exact=True).wait_for()
                    report['db_before']=await asyncio.to_thread(db_snapshot)
                    async def open_preview(label='Open preview'):
                        await page.get_by_role('button',name=label,exact=True).click(); await page.get_by_test_id('gate-preview').wait_for(); return page.get_by_test_id('gate-preview')
                    gate=await open_preview()
                    await gate.get_by_text('Main entrance',exact=True).wait_for()
                    await gate.locator('input[type=file]').set_input_files({'name':'bad.txt','mimeType':'text/plain','buffer':b'not an image'})
                    await gate.get_by_role('alert').filter(has_text='Choose a readable').wait_for(); report['checks'].append('invalid upload refused')
                    await gate.get_by_role('button',name='Use camera',exact=True).click()
                    await gate.get_by_text('Camera unavailable.',exact=False).wait_for(timeout=20000); report['checks'].append('camera unavailable upload fallback')
                    portrait=await page.evaluate('''()=>{const c=document.createElement('canvas');c.width=480;c.height=640;const x=c.getContext('2d');x.fillStyle='#dfe7d5';x.fillRect(0,0,480,640);x.fillStyle='#778b65';x.beginPath();x.arc(240,236,90,0,Math.PI*2);x.fill();x.beginPath();x.ellipse(240,575,165,190,0,0,Math.PI*2);x.fill();x.fillStyle='#f8faf5';x.font='20px sans-serif';x.textAlign='center';x.fillText('SYNTHETIC PREVIEW',240,610);return c.toDataURL('image/png').split(',')[1]}''')
                    await gate.locator('input[type=file]').set_input_files({'name':'synthetic-preview.png','mimeType':'image/png','buffer':base64.b64decode(portrait)})
                    await gate.locator('img').wait_for(); await gate.get_by_role('button',name='Select all',exact=True).click()
                    await gate.get_by_role('button',name='Review change',exact=True).click(); await gate.get_by_text('Choose a photo and complete both review checks.',exact=True).wait_for()
                    await gate.get_by_label('Face is straight and fully visible',exact=True).check(); await gate.get_by_label('Eyes are open; the picture is clear',exact=True).check()
                    await gate.get_by_role('button',name='Review change',exact=True).click(); await gate.get_by_role('region',name='Confirm selected change').wait_for()
                    await page.keyboard.press('Tab'); assert await gate.evaluate('(e)=>e.contains(document.activeElement)'), 'Focus escaped confirmation'
                    await call(s,'qa_browser',{'tool':'emulate','arguments':{'pageId':pageid,'viewport':'1280x800x1'}})
                    async def browser_shot(filename):
                        await page.bring_to_front()
                        bound=await call(s,'qa_browser',{'tool':'take_snapshot','arguments':{'pageId':pageid}})
                        assert '910001' in text(bound),'Screenshot target is not the tested ERP employee'
                        result=await call(s,'qa_browser',{'tool':'take_screenshot','arguments':{'pageId':pageid,'format':'png'}})
                        images=[c for c in result.content if c.type=='image']; assert images,'Browser screenshot image missing'
                        decoded=base64.b64decode(images[0].data); assert len(decoded)>15000,'Blank screenshot evidence refused'
                        (OUT/filename).write_bytes(decoded)
                    await page.bring_to_front()
                    native=await call(s,'qa_desktop',{'tool':'screenshot','arguments':{'pid':state['chrome_pid'],'max_width':1600,'max_height':1200}})
                    native_images=[c for c in native.content if c.type=='image']; assert native_images
                    (OUT/'desktop-review-native.png').write_bytes(base64.b64decode(native_images[0].data))
                    await gate.evaluate('(e)=>{e.parentElement.scrollTop=0}')
                    await browser_shot('desktop-review.png')
                    await gate.get_by_role('button',name='Apply to turnstiles',exact=True).click(); await gate.get_by_text('Partial completion',exact=True).wait_for()
                    assert await gate.get_by_text('Verified in simulation',exact=True).count()==3
                    assert await gate.locator('[data-gate-result]').get_by_text('Waiting for device',exact=True).count()==1
                    report['checks'].append('explicit apply: 3 verified, 1 waiting; no device writes')
                    await browser_shot('desktop-results.png')
                    shot=await call(s,'qa_desktop',{'tool':'screenshot','arguments':{'pid':state['chrome_pid'],'max_width':1600,'max_height':1200}})
                    images=[c for c in shot.content if c.type=='image']; assert images; (OUT/'desktop-native.png').write_bytes(base64.b64decode(images[0].data))
                    await gate.get_by_role('button',name='Simulate device reconnect',exact=True).click(); assert await gate.get_by_text('Verified in simulation',exact=True).count()==4
                    await gate.get_by_role('button',name='Close',exact=True).click(); gate=await open_preview(); await gate.get_by_text('Simulation complete',exact=True).wait_for(); report['checks'].append('reconnect and reopen preserve simulated history')
                    await gate.get_by_role('button',name='Revoke access',exact=True).click(); await gate.get_by_role('button',name='Select all',exact=True).click(); await gate.get_by_role('button',name='Review change',exact=True).click()
                    await gate.get_by_role('button',name='Revoke access',exact=True).last.click(); await gate.get_by_text('Partial completion',exact=True).wait_for(); assert await gate.get_by_text('Revoked in simulation',exact=True).count()==3
                    report['checks'].append('revoke independent from HR archive')
                    await gate.get_by_role('button',name='Edit details',exact=True).click(); await gate.get_by_role('button',name='Review change',exact=True).click(); await gate.get_by_role('button',name='Apply to turnstiles',exact=True).click()
                    await gate.locator('button[aria-pressed]').filter(has_text='Revoke access').last.click()
                    await gate.get_by_text('Superseded by a later change',exact=True).wait_for(); assert await gate.get_by_role('button',name='Simulate device reconnect',exact=True).count()==0
                    report['checks'].append('older pending operation selectable; overlapping late action superseded')
                    await gate.get_by_role('button',name='Close',exact=True).click()
                    row=page.get_by_role('row').filter(has_text='Preview - Missing employee number'); await row.get_by_role('button',name='Turnstile access',exact=True).click(); gate=page.get_by_test_id('gate-preview')
                    await gate.get_by_text('Save a real employee number',exact=False).wait_for(); assert await gate.get_by_role('button',name='Review change',exact=True).is_disabled(); await gate.get_by_role('button',name='Close',exact=True).click(); report['checks'].append('missing real employee number blocked')
                    for lang,label,title in [('ru','Открыть макет','Доступ через турникет'),('uz','Namunani ochish','Turniketga kirish'),('en','Open preview','Turnstile access')]:
                        await page.evaluate('(lang)=>localStorage.setItem("erp_lang",lang)',lang); await page.reload()
                        emulation=await call(s,'qa_browser',{'tool':'emulate','arguments':{'pageId':pageid,'viewport':'390x844x1,mobile,touch'}})
                        (OUT/('emulation-'+lang+'.txt')).write_text(text(emulation))
                        # Synchronize the external Playwright connection with the QA browser's actual mobile metrics.
                        await device_session.send('Emulation.setDeviceMetricsOverride',{'width':390,'height':844,'screenWidth':390,'screenHeight':844,'deviceScaleFactor':1,'mobile':True})
                        await device_session.send('Emulation.setTouchEmulationEnabled',{'enabled':True,'maxTouchPoints':1})
                        await page.wait_for_function('screen.width===390 && innerWidth===390',timeout=20000)
                        gate=await open_preview(label)
                        metrics=await page.evaluate('({screen:screen.width,inner:innerWidth,client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})')
                        assert metrics['screen']==390 and metrics['inner']==390,metrics
                        bounds=await gate.bounding_box(); assert bounds and bounds['x']>=0 and bounds['x']+bounds['width']<=390,bounds
                        await browser_shot('mobile-'+lang+'.png')
                        report['checks'].append({'locale':lang,'metrics':metrics,'panel':bounds})
                        # Escape closes the dialog in all languages, restoring the directory.
                        await page.keyboard.press('Escape'); await gate.wait_for(state='detached')
                    async def viewer_me(route):
                        response=await route.fetch(); body=await response.json(); body['permissions']=['hr.employees','attendance.view']; await route.fulfill(response=response,json=body)
                    await context.route('**/api/auth/me',viewer_me); await page.reload(); gate=await open_preview()
                    await gate.get_by_text('You can inspect this preview.',exact=False).wait_for(); assert await gate.get_by_role('button',name='Review change',exact=True).is_disabled()
                    await context.unroute('**/api/auth/me',viewer_me); report['checks'].append('frontend viewer cannot simulate writes')
                    report['db_after']=await asyncio.to_thread(db_snapshot); assert report['db_before']==report['db_after'],'Preview changed business rows'
                    assert not console,console; assert not blocked,blocked; assert not failed,failed
                    report.update(page_errors=console,http_failures=failed,external_requests=blocked)
                    await call(s,'qa_browser',{'tool':'list_console_messages','arguments':{'pageId':pageid,'types':['error','warn']}})
                    await call(s,'qa_browser',{'tool':'list_network_requests','arguments':{'pageId':pageid,'pageSize':20}})
                await call(s,'qa_stop',{}); report['owned_lane_cleanup']=True
        report['status']='PASSED'
    except BaseException as e: report.update(status='FAILED',error=repr(e)); raise
    finally:
        (OUT/('report-'+str(time.time_ns())+'.json')).write_text(json.dumps(report,indent=2)); (OUT/'report.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2),flush=True)

asyncio.run(main())
