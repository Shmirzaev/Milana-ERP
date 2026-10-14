import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { chromium } from 'playwright';
const root = process.cwd();
const stubs = {
  '@/lib/auth': `export const useMe=()=>({me:window.testMe});export const can=me=>!!me?.permissions.includes('packaging.packages');`,
  '@/lib/i18n': `export const useT=()=>({lang:window.testLang||'en'});`,
  '@/lib/api': `export const fetcher=async path=>{window.reads.push(path);return window.balance;};export const api={put:async(path,body)=>{window.writes.push({path,body});window.balance={...window.balance,needs_size_entry:false,version:'b'.repeat(64),sizes:body.sizes.map(row=>({...row,accepted:row.quantity,packed:row.size==='S'?3:0,remaining:row.quantity-(row.size==='S'?3:0)}))};return window.balance;}};`,
  '@/components/PendingPackageWorkflow': `export default function Pending(){return null;}`,
  '@/lib/packageWorkflow': `export const postPackageWorkflow=async(path,body)=>{window.packages.push({path,body});return {id:1};};`,
};
const result = await build({stdin:{contents:`import React from 'react';import {createRoot} from 'react-dom/client';import FirstGrade from './src/components/FirstGradePackaging';createRoot(document.getElementById('root')).render(<FirstGrade productionOrderId={301} batchId={139} modelId={1} color="White" onChanged={async()=>{}}/>);`,resolveDir:root,loader:'tsx'},bundle:true,write:false,format:'iife',jsx:'automatic',plugins:[{name:'fixtures',setup(b){
  b.onResolve({filter:/^@\//},a=>a.path in stubs?{path:a.path,namespace:'fixtures'}:undefined);
  b.onLoad({filter:/.*/,namespace:'fixtures'},a=>({contents:stubs[a.path],loader:'tsx',resolveDir:root}));
}}]});
const browser = await chromium.launch({channel:process.platform==='win32'?'chrome':undefined});
try {
  const page = await browser.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://localhost:3198/**',route=>route.fulfill({contentType:'text/html',body:'<div id="root"></div>'}));
  async function load(lang='en',permissions=['packaging.packages']) {
    await page.goto('http://localhost:3198/');
    await page.evaluate(({lang,permissions})=>Object.assign(window,{testLang:lang,testMe:{id:9,permissions},reads:[],writes:[],packages:[],balance:{needs_size_entry:true,total:8,version:'a'.repeat(64),sizes:[{size:'M',accepted:null,packed:0,remaining:0},{size:'S',accepted:null,packed:3,remaining:0}]}}),{lang,permissions});
    await page.addScriptTag({content:result.outputFiles[0].text});
  }
  await load();
  await page.getByRole('button',{name:'1st Grade — singles'}).click();
  const save=page.getByRole('button',{name:'Save size quantities'});
  await save.waitFor();assert.equal(await save.isDisabled(),true);
  await page.getByLabel('Accepted from sewing S').fill('2');
  await page.getByLabel('Accepted from sewing M').fill('6');
  assert.equal(await save.isDisabled(),true,'Cannot reduce a size below already packed');
  await page.getByLabel('Accepted from sewing S').fill('5');
  assert.equal(await save.isDisabled(),true,'Must match accepted total');
  await page.getByLabel('Accepted from sewing M').fill('3');
  await save.click();
  const singles=page.getByLabel('Singles to pack S');await singles.waitFor();
  assert.equal(await singles.getAttribute('max'),'2');
  await singles.fill('2');await page.getByRole('button',{name:'Create singles and labels (2/200)'}).click();
  await page.waitForFunction(()=>window.packages.length===1);
  const calls=await page.evaluate(()=>({reads:window.reads,writes:window.writes,packages:window.packages}));
  assert.equal(calls.writes.length,1);assert.match(calls.writes[0].path,/size-entry\/301\?production_batch_id=139$/);
  assert.equal(calls.packages[0].body.packages.length,2);
  assert.ok(calls.reads.every(path=>path.startsWith('/api/packages/')),'No Sewing navigation/API needed');
  for (const lang of ['ru','uz']) {
    await load(lang);await page.getByRole('button').first().click();
    await page.locator('input').first().waitFor();
    assert.equal(await page.locator('input').count(),2);
    assert.ok(!(await page.locator('body').innerText()).includes('Enter the accepted'));
  }
  await load('en',[]);assert.equal(await page.locator('button').count(),0);
  assert.deepEqual(errors,[]);
  console.log('Packaging size entry: total/packed limits, save-to-singles transition, batch identity, EN/RU/UZ and permissions passed.');
} finally { await browser.close(); }
