import assert from 'node:assert/strict';
import fs from 'node:fs';
import {build} from 'esbuild';
import {chromium} from 'playwright';
import postcss from 'postcss';
import tailwind from 'tailwindcss';
import autoprefixer from 'autoprefixer';
const stubs={
 '@/lib/auth':`export const useMe=()=>({me:{permissions:[]}});export const can=()=>false;`,
 '@/lib/api':`export const fetcher=async url=>url.includes('print-runs')?window.runs:{cells:[]};export const api={get:async url=>url.includes('resolve')?null:window.pkg,openLabel:async()=>{},post:async()=>{throw Error('Unexpected write')},del:async()=>{throw Error('Unexpected write')}};`,
 '@/components/WarehouseMap':`export default function Map(){return null}`,
 '@/components/ManualPackageReceipt':`export default function Receipt(){return null}`,
 'next/navigation':`export const useRouter=()=>({push(){}});export const usePathname=()=>'/packages/scan';`,
 'next/link':`export default function Link({children,...props}){return <a {...props}>{children}</a>}`,
};
const built=await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import {LangProvider} from './src/lib/i18n';import {DialogProvider} from './src/components/DialogProvider';import Page from './src/app/(app)/packages/scan/page';createRoot(document.getElementById('root')).render(<LangProvider><DialogProvider><Page/></DialogProvider></LangProvider>);`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',plugins:[{name:'fixtures',setup(b){b.onResolve({filter:/.*/},a=>a.path in stubs?{path:a.path,namespace:'fixture'}:undefined);b.onLoad({filter:/.*/,namespace:'fixture'},a=>({contents:stubs[a.path],loader:'tsx',resolveDir:process.cwd()}));}}]});
const css=(await postcss([tailwind(),autoprefixer()]).process(fs.readFileSync('src/app/globals.css','utf8'),{from:'src/app/globals.css'})).css;
const browser=await chromium.launch({channel:process.platform==='win32'?'chrome':undefined});
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://localhost:3199/**',route=>route.fulfill({contentType:'text/html',body:'<div id="root"></div>'}));
 for(const lang of ['en','ru','uz']) for(const width of [1280,390]){
  await page.setViewportSize({width,height:1000});await page.goto('http://localhost:3199/test');
  await page.evaluate(({lang})=>{localStorage.setItem('erp_lang',lang);window.runs=[{id:1,run_no:'PRN-2026-000015',created_at:'2026-10-13T05:00:00Z',count:4,quantity:360,received_at:null,package_ids:[],packages:[],model_codes:['BJ5030-5796','PJ1244-V-6230']}];window.pkg={id:1,package_no:'PKG-00059',model_code:'BJ5030-5796',model_name:'Бамбук штаны с длинным названием',total_quantity:60,color:'white',status:'received_in_storage'};},{lang});
  await page.addStyleTag({content:css});await page.addScriptTag({content:built.outputFiles[0].text});
  await page.getByText('BJ5030-V-5796',{exact:true}).waitFor();await page.getByText('PJ1244-V-6230',{exact:true}).waitFor();
  const input=page.locator('input').first();await input.fill('PKG-00059');await input.press('Enter');
  const row=page.locator('tr').filter({hasText:'Бамбук штаны с длинным названием'});await row.waitFor();
  const cells=await row.locator('td').evaluateAll(elements=>elements.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,scroll:e.scrollWidth,width:e.clientWidth}}));
  assert.ok(cells[3].right<=cells[4].left+1,'Model and quantity columns do not overlap');assert.ok(cells[3].scroll<=cells[3].width+1,'Model text stays within its cell');
 }
 assert.deepEqual(errors,[]);console.log('Package scan alignment and multi-model print runs passed at desktop/phone sizes in EN/RU/UZ.');
}finally{await browser.close();}
