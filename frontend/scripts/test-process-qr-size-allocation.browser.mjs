// Real Process QR React/SWR page with disposable HTTP fixtures; no ERP connection.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { execFileSync } from "node:child_process";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";
const root = process.cwd();
const out = path.resolve(root, "../outputs/size-allocation-qa");
fs.mkdirSync(out, { recursive: true });
const dictionaries = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, Object.fromEntries(runtimeMessages(lang))]));
const mocks = {
  "@/lib/i18n": `const dict=${JSON.stringify(dictionaries)}; export const useT=()=>({lang:new URLSearchParams(location.search).get('lang')||'en',t:(key,args={})=>{let text=dict[new URLSearchParams(location.search).get('lang')||'en'][key]||key;for(const [k,v] of Object.entries(args))text=text.replaceAll('{'+k+'}',String(v));return text;}});`,
  "@/lib/auth": `export const useMe=()=>({me:{id:1,factory_code:'MIL',permissions:['*']}}); export const can=()=>true; export const logout=()=>{};`,
  "@/components/DialogProvider": `export const useDialogs=()=>({confirm:async()=>false,alert:async()=>{}});`,
  "next/link": `import React from 'react'; export default function Link({children,...props}){return React.createElement('a',props,children)}`,
  "@/lib/api": `export async function fetchResponse(url,opts){return fetch(url,opts)};export const fetcher=async url=>{const r=await fetch(url);if(!r.ok)throw Error('Fixture HTTP '+r.status);return r.json()};export const api={get:fetcher,post:async(url,body)=>{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('Fixture write failed');return r.json()},patch:async()=>{throw Error('Unexpected patch')},delete:async()=>{throw Error('Unexpected delete')}};`,
};
const built = await build({stdin:{contents:`import React from 'react';import{createRoot}from'react-dom/client';import Page from './src/app/(app)/process-qr/page';createRoot(document.getElementById('root')).render(<Page/>);`,resolveDir:root,loader:"tsx"},bundle:true,write:false,format:"iife",jsx:"automatic",plugins:[{name:"fixture",setup(b){
 b.onResolve({filter:/^(?:@\/lib\/(?:api|auth|i18n)|@\/components\/DialogProvider|next\/link)$/},args=>({path:args.path,namespace:"fixture"}));
 b.onLoad({filter:/.*/,namespace:"fixture"},args=>({contents:mocks[args.path],loader:"js",resolveDir:root}));
 b.onLoad({filter:/process-qr[\\/]page\.tsx$/},args=>({contents:fs.readFileSync(args.path,"utf8").replaceAll('<style jsx global>', '<style>'),loader:"tsx",resolveDir:path.dirname(args.path)}));
}}]});
const css=execFileSync(process.execPath,['node_modules/tailwindcss/lib/cli.js','-i','src/app/globals.css','--minify'],{encoding:'utf8',maxBuffer:8*1024*1024,stdio:['ignore','pipe','pipe']});
const sizes=["46","48","50","52","54"];
const operation={id:'sleeve',name:'Sleeve sewing',code:'OP-6162',section:'sewing',sewingFactory:'milana',rate:'550',selected:true,copies:1,splitMode:'none'};
const model={id:8456,code:'KJ13051-V-6472',sizes:sizes.map(size=>({size})),details_json:{paid_operations:[operation]}};
const batches=[{id:189,batch_no:'0319-01',batch_index:1,name:'Nastil 1',planned_quantity:300,sewing_completed_quantity:300,sewing_sizes:[]},{id:192,batch_no:'0319-02',batch_index:2,name:'Nastil 2',planned_quantity:300,sewing_completed_quantity:302,sewing_sizes:[]}];
let issued=[], posts=[], requests=[], modelDelay=120;
const fixtureOrder={production_order_id:319,production_no:'PO-0294',model_id:8456,model_code:model.code,planned_quantity:600,sewing_completed_quantity:602,sizes:sizes.map(size=>({size,planned_quantity:120,sewing_completed_quantity:0})),batches,stages:[],sewing_factories:[{code:'MIL'}]};
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://local');
 if(url.pathname.startsWith('/api/')){
  requests.push({method:req.method,url:url.pathname});res.setHeader('Content-Type','application/json');
  if(req.method==='POST' && url.pathname==='/api/payroll/qr-labels/issue'){
   let body='';for await(const part of req)body+=part;const data=JSON.parse(body);posts.push(data);
   issued.push(...data.labels.map((row,index)=>({...row,id:issued.length+index+1,status:'available',qr_token:String(200000000+issued.length+index),issued_at:new Date().toISOString()})));
   res.end(JSON.stringify({created_count:data.labels.length,labels:issued}));return;
  }
  if(req.method!=='GET'){res.statusCode=500;res.end('{}');return;}
  let data=[];
  if(url.pathname==='/api/process-tracking')data=[fixtureOrder];
  else if(url.pathname==='/api/models/8456'){await new Promise(r=>setTimeout(r,modelDelay));data=model;}
  else if(url.pathname==='/api/sewing-flows')data=[{id:6,code:'SEW-06',name:'Line 6',is_active:true,factory_code:'MIL'}];
  else if(url.pathname==='/api/payroll/qr-labels')data={items:issued,total:issued.length};
  res.end(JSON.stringify(data));return;
 }
 res.setHeader('Content-Type','text/html;charset=utf-8');res.end(`<html><head><meta name="viewport" content="width=device-width, initial-scale=1"/><style>${css}</style></head><body><main style="padding:20px"><div id="root"></div></main><script>${built.outputFiles[0].text.replaceAll('</script>','<\\/script>')}</script></body></html>`);
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const browser=await chromium.launch({channel:process.platform==='win32'?'chrome':undefined,headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
const url=`http://127.0.0.1:${server.address().port}`;
try{
 await page.goto(url);await page.getByRole('heading',{name:'0319-01 · Nastil 1',exact:true}).waitFor();
 const panel=()=>page.getByRole('heading',{name:dictionaries.en['page.processQr.sizeQuantities'],exact:true}).locator('../..').locator('..');
 const inputs=()=>panel().getByRole('spinbutton');
 await page.waitForFunction(()=>[...document.querySelectorAll('input[type=number]')].filter(e=>e.value==='60').length>=5);
 assert.equal(await inputs().count(),5);assert.deepEqual(await inputs().evaluateAll(nodes=>nodes.map(n=>n.value)),['60','60','60','60','60']);
 // The sewing line remains an explicit operator selection.
 await page.locator('select').filter({has:page.locator('option[value="6"]')}).selectOption('6');
 const issue=()=>page.getByRole('button',{name:'Issue labels',exact:true}).first();
 await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Issue labels'&&!b.disabled));
 await inputs().nth(0).fill('50');assert.equal(await issue().isDisabled(),true);
 await inputs().nth(1).fill('70');assert.equal(await issue().isEnabled(),true);
 await page.getByRole('button',{name:'All batches',exact:true}).click();
 assert.equal(await inputs().count(),10);
 assert.deepEqual(await inputs().evaluateAll(nodes=>nodes.map(n=>n.value)),['50','70','60','60','60','61','61','60','60','60']);
 await inputs().nth(5).fill('');assert.equal(await issue().isDisabled(),true);
 await inputs().nth(5).fill('61');assert.equal(await issue().isEnabled(),true);
 await panel().screenshot({path:path.join(out,'editable-size-split.png')});
 await issue().click();await page.waitForFunction(()=>document.body.textContent.includes('200000000'));
 assert.equal(posts.length,1);assert.equal(posts[0].labels.length,10);
 assert.deepEqual(posts[0].labels.filter(row=>row.production_batch_id===189).map(row=>row.quantity),[50,70,60,60,60]);
 assert.equal(posts[0].labels.filter(row=>row.production_batch_id===192).reduce((sum,row)=>sum+row.quantity,0),302);
 assert.equal(await issue().isDisabled(),true);
 // Editing an issued allocation must not silently issue a conflicting partial set.
 await inputs().nth(0).fill('60');await inputs().nth(1).fill('60');assert.equal(await issue().isDisabled(),true);
 assert.ok((await panel().innerText()).includes('differs from already issued'));
 // Real translations and narrow-screen layout use the same live component tree.
 for(const lang of ['ru','uz']){
  issued=[];await page.setViewportSize({width:390,height:844});await page.goto(url+'?lang='+lang);
  await page.waitForFunction(()=>[...document.querySelectorAll('input[type=number]')].filter(e=>e.value==='60').length>=5);
  assert.ok((await page.locator('body').innerText()).includes(dictionaries[lang]['page.processQr.autoSizeSplit']));
  const sizePanel=page.getByRole('heading',{name:dictionaries[lang]['page.processQr.sizeQuantities'],exact:true}).locator('../..').locator('..');
  const bounds=await sizePanel.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=391);
  await sizePanel.screenshot({path:path.join(out,`size-split-${lang}-mobile.png`)});
 }
 // Fully recorded output remains authoritative and cannot be edited here.
 batches[0].sewing_sizes=[{size:'46',sewing_completed_quantity:200},{size:'48',sewing_completed_quantity:100}];
 await page.goto(url);await page.waitForFunction(()=>[...document.querySelectorAll('input[type=number]')].some(e=>e.value==='200'));
 assert.equal(await inputs().count(),2);
 assert.deepEqual(await inputs().evaluateAll(nodes=>nodes.map(n=>[n.value,n.readOnly])),[['200',true],['100',true]]);
 assert.deepEqual(errors,[]);
 assert.ok(requests.filter(r=>r.method!=='GET').every(r=>r.method==='POST'&&r.url==='/api/payroll/qr-labels/issue'));
 console.log('PASS: actual Process QR page auto-splits, preserves edits across all-batch mode, gates invalid totals, issues exact edited payloads, blocks issued conflicts, and renders EN/RU/UZ on desktop/mobile. Fixture writes only.');
}finally{await browser.close();await new Promise(r=>server.close(r));}
