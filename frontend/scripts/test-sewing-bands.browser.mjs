import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium } from 'playwright';
import postcss from 'postcss';
import tailwind from 'tailwindcss';
import autoprefixer from 'autoprefixer';
const root=process.cwd();
const stubs={
  '@/lib/auth': `import {useEffect,useState} from 'react'; export const logout=()=>{}; export const useMe=()=>{const [ready,setReady]=useState(false);useEffect(()=>{const id=setTimeout(()=>setReady(true),25);return()=>clearTimeout(id)},[]);return {me:ready?window.me:undefined,loading:!ready,hasToken:ready?true:undefined,refresh:async()=>{}}}; export const can=(me,...perms)=>!!me?.permissions.some(p=>p==='*'||perms.includes(p));`,
  'next/navigation': `const router={push:p=>window.navigations.push(p),replace:p=>window.navigations.push(p)}; const params=new URLSearchParams(window.testPath.split('?')[1]||''); export const usePathname=()=>window.testPath.split('?')[0]; export const useSearchParams=()=>params; export const useParams=()=>({id:'81',code:'ECO'}); export const useRouter=()=>router;`,
  'next/link': `export default function Link({children,...props}) {return <a {...props}>{children}</a>}`,
  '@/lib/api': `export async function fetcher(url){window.reads.push(url);
    if(url==='/api/sewing-bands/orders')return window.orders;
    if(url==='/api/sewing-bands')return window.bands;
    if(url.startsWith('/api/sewing-bands/receive-options'))return window.options;
    if(url.startsWith('/api/sewing-daily-reports/line-context'))return window.line;
    if(url.startsWith('/api/sewing-daily-reports?'))return {rows:[],summary:[],total_sewn_qty:0,total_defective_qty:0};
    throw Error('Unexpected unscoped read: '+url);}
    async function post(path,body,headers){window.calls.push({path,body,headers});if(window.failOnce){window.failOnce=false;throw Error('Network interrupted');}return {received_count:1};}
    export const api={post,postWithHeaders:post,patch:post,get:fetcher,del:post}; export const fetchResponse=async()=>{throw Error('Unexpected export')};`,
};
const entry=`import React from 'react';import {createRoot} from 'react-dom/client';
import Providers from './src/components/Providers';import Shell from './src/components/AppShell';import Gate from './src/components/AuthGate';
import Flows from './src/app/(app)/sewing/flows/page';import Reports from './src/app/(app)/sewing/daily-report/page';
import Scan from './src/app/(app)/bundles/scan/sewing/page';import Floor from './src/app/(app)/departments/[code]/page';import Order from './src/app/(app)/work-orders/[id]/sewing/page';
const Page=window.testPath.includes('daily-report')?Reports:window.testPath.includes('bundles')?Scan:window.testPath.includes('departments')?Floor:window.testPath.includes('work-orders')?Order:Flows;
createRoot(document.getElementById('root')).render(<Providers><Gate><Shell><Page/></Shell></Gate></Providers>);`;
const built=await build({stdin:{contents:entry,resolveDir:root,loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',plugins:[{name:'fixtures',setup(b){
  b.onResolve({filter:/^(?:@\/|next\/)/},a=>a.path in stubs?{path:a.path,namespace:'fixtures'}:undefined);
  b.onLoad({filter:/.*/,namespace:'fixtures'},a=>({contents:stubs[a.path],loader:'tsx',resolveDir:root}));
}}]});
const css=(await postcss([tailwind(),autoprefixer()]).process(fs.readFileSync('src/app/globals.css','utf8'),{from:'src/app/globals.css'})).css;
const job={id:41,work_order_id:81,production_order_id:71,production_batch_id:91,order_no:'PO-100',model:'1001-1',batch:'Kroy 1',quantity:100,reported_qty:40,actual_qty:0,top_qty:40,bottom_qty:40,line_finished:false,awaiting_final:false,finish_reason:null,status:'planned'};
const work={...job,sewing_assignment_id:41,model_no:'1001',variant_no:'1',batch_no:'Kroy 1',planned_qty:100,completed_qty:0,remaining_qty:100,report_remaining_top_qty:60,report_remaining_bottom_qty:60};
const me={id:9,name:'Band 1',sewing_band_id:64,factory_code:'ECO',available_factories:['ECO'],role:'Eco Band',permissions:['sewing.workspace','sewing.bundles','sewing.records'],access_configured:true};
const browser=await chromium.launch({channel:process.platform==='win32'?'chrome':undefined});
try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});
  await page.route('http://localhost:3199/**',route=>{
    const url=new URL(route.request().url());
    if(url.pathname.startsWith('/branding/'))return route.fulfill({contentType:'image/svg+xml',body:fs.readFileSync(path.join(root,'public',url.pathname))});
    return route.fulfill({contentType:'text/html',body:'<div id="root"></div>'});
  });
  const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
  async function load(options={}){
    await page.goto('http://localhost:3199/band-test');
    await page.evaluate(opts=>{Object.assign(window,opts);localStorage.setItem('erp_lang',opts.testLang||'en');},{calls:[],reads:[],navigations:[],me,testPath:'/sewing/flows?factory=ECO',bands:[{id:64,name:'1-Band',code:'ECO-01',jobs:[job]}],orders:[{...job,sewing_assignment_id:41,model_no:'1001',variant_no:'1',planned_output_qty:100,passed_qty:0,operation:'sewing'}],line:{sewing_flow_id:64,line_code:'ECO-01',line_name:'1-Band',active_work_orders:[work]},options:[{production_order_id:71,production_batch_id:91,model_id:1,order_no:'PO-100',model_code:'1001-1',batch_label:'Kroy 1',quantity:100,bundle_count:10}],...options});
    await page.addStyleTag({content:css});await page.addScriptTag({content:built.outputFiles[0].text});await page.locator('main h1').waitFor();
    assert.equal(await page.locator('aside:visible nav a').count(),4);assert.equal(await page.locator('aside:visible img').count(),1);
    await page.waitForTimeout(100);
    assert.deepEqual(await page.evaluate(()=>window.reads.filter(url=>!url.startsWith('/api/sewing-bands')&&!url.startsWith('/api/sewing-daily-reports'))),[],'No unscoped reads while session identity resolves');
  }
  await load();await page.getByText('Reported progress: 40 / 100',{exact:false}).waitFor();
  await page.getByRole('button',{name:'Enter final output',exact:true}).click();
  await page.getByLabel('Accepted pieces',{exact:true}).fill('40');await page.getByRole('button',{name:'Save actual order output',exact:true}).click();
  await page.waitForFunction(()=>window.calls.length===1);assert.equal((await page.evaluate(()=>window.calls[0])).body.sewing_assignment_id,41);
  await load({testPath:'/sewing/daily-report?factory=ECO',failOnce:true});
  await page.waitForFunction(()=>document.getElementById('daily-sewing-line')?.value==='64');
  assert.equal(await page.locator('#daily-sewing-line').isDisabled(),true);assert.equal(await page.locator('#daily-sewing-line option').count(),1);
  await page.locator('input[id^="daily-sewing-section-"][type="number"]').first().fill('25');
  const save=page.locator('main section').first().locator('button.btn-primary').last();await save.click();await page.getByText('Network interrupted',{exact:true}).waitFor();await save.click();
  await page.waitForFunction(()=>window.calls.length===2);const writes=await page.evaluate(()=>window.calls);
  assert.equal(writes[0].body.sewing_flow_id,64);assert.equal(writes[0].body.sewing_assignment_id,41);assert.equal(writes[0].headers['Idempotency-Key'],writes[1].headers['Idempotency-Key']);
  await load({bands:[{id:64,name:'1-Band',code:'ECO-01',jobs:[{...job,reported_qty:100,line_finished:true,awaiting_final:true}]}]});
  await page.getByText('Available — needs work',{exact:true}).waitFor();await page.locator('summary').click();await page.getByText('Awaiting final order output',{exact:true}).waitFor();
  await load({testPath:'/bundles/scan/sewing?factory=ECO'});await page.locator('#bundle-scan-sewing').fill('BUNDLE-123');await page.getByRole('button',{name:'Receive and assign to my band',exact:true}).click();
  await page.waitForFunction(()=>window.calls.length===1);assert.deepEqual((await page.evaluate(()=>window.calls[0])).body,{code:'BUNDLE-123'});assert.equal(await page.locator('.scan-workspace').count(),1);
  await load({testPath:'/departments/ECO'});await page.locator('main table').waitFor();assert.match(await page.locator('main a').last().getAttribute('href'),/\/work-orders\/81\/sewing\?assignment=41/);
  await load({testPath:'/work-orders/81/sewing?assignment=41'});await page.getByRole('progressbar').waitFor();
  for(const testLang of ['ru','uz']){await load({testPath:'/sewing/daily-report?factory=ECO',testLang});await page.waitForFunction(()=>document.getElementById('daily-sewing-line')?.value==='64');}
  await load({testPath:'/bundles/scan/sewing?factory=ECO'});
  const output=path.resolve(root,'../outputs/band-preview');fs.mkdirSync(output,{recursive:true});await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Menu',exact:true}).click();assert.equal(await page.locator('#mobile-navigation nav a').count(),4);
  await page.locator('#mobile-navigation').getByRole('button',{name:'Close menu',exact:true}).click();await page.screenshot({path:path.join(output,'phone.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
  console.log('ERP shell, actual sewing pages, fixed line, scoped reads, report retry, output, scanner, history, EN/RU/UZ and mobile navigation passed.');
}finally{await browser.close();}
