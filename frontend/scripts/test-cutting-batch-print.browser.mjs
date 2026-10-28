// Exercise the real Cutting page and confirmation dialog against disposable HTTP data.
import assert from "node:assert/strict";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const messages = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, Object.fromEntries(runtimeMessages(lang))]));
const stubs = {
  "next/navigation": `export const useParams=()=>({id:'1260'});export const usePathname=()=>location.pathname;`,
  "@/lib/auth": `export const useMe=()=>({me:{id:1,permissions:['*']}});export const can=()=>true;`,
  "@/components/CuttingSewingFactory": `export default function Factory(){return null}`,
  "@/components/WorkOrderProductInfo": `export default function Product(){return null}`,
  "@/components/PageHeader": `export default function Header(){return null}`,
  "@/lib/api": `export const fetcher=async url=>{const r=await fetch(url);if(!r.ok)throw Error('Fixture rejection');return r.json()};async function write(method,url,body){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('Fixture rejection');return r.json()}export const api={get:fetcher,post:(u,b)=>write('POST',u,b),patch:(u,b)=>write('PATCH',u,b),put:(u,b)=>write('PUT',u,b),del:u=>write('DELETE',u),openLabel:async u=>window.printedUrls.push(u)};`,
};
const bundle = await build({ stdin: { resolveDir: root, loader: "tsx", contents: `
import React from 'react';import{createRoot}from'react-dom/client';
import Page from './src/app/(app)/work-orders/[id]/cutting/page';
import{LangProvider}from'./src/lib/i18n';import{DialogProvider}from'./src/components/DialogProvider';
window.printedUrls=[];localStorage.setItem('erp_lang',new URLSearchParams(location.search).get('lang')||'en');
createRoot(document.getElementById('root')).render(<LangProvider><DialogProvider><Page/></DialogProvider></LangProvider>);` },
  bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
    b.onResolve({ filter: /^(?:@\/|next\/)/ }, args => args.path in stubs ? { path: args.path, namespace: "fixture" } : undefined);
    b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: stubs[args.path], loader: "tsx", resolveDir: root }));
  } }],
});
const batches = [{ id: 180, batch_no: "0321-01", name: "Nastil 1", batch_index: 1, planned_quantity: 486 },
  { id: 186, batch_no: "0321-02", name: "Extra batch 2", batch_index: 2, planned_quantity: 0 }];
const writes = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname === "/fixture.js") { res.setHeader("Content-Type", "text/javascript"); res.end(bundle.outputFiles[0].text); return; }
  if (!url.pathname.startsWith("/api/")) {
    res.setHeader("Content-Type", "text/html");
    res.end('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>'); return;
  }
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") {
    let raw = ""; for await (const part of req) raw += part;
    writes.push({ method: req.method, path: url.pathname, body: raw ? JSON.parse(raw) : null });
    res.end(JSON.stringify({ id: 319, bundles: [] })); return;
  }
  let data = [];
  if (url.pathname === "/api/work-orders/1260") data = { id: 1260, production_order_id: 321, operation: "cutting", status: "in_progress", department_id: 1, planned_output_qty: 600, passed_qty: 0 };
  if (url.pathname === "/api/production-orders/321") data = { id: 321, production_no: "PO-0296", source_type: "standard", planned_quantity: 600, model_id: 1, batches, items: [48, 50, 52, 54, 56, 58].map(size => ({ color: "white", size: String(size), planned_quantity: 81 })), materials: [] };
  if (url.pathname === "/api/models/1") data = { id: 1, bom: [] };
  if (url.pathname === "/api/departments") data = [{ id: 1, code: "CUT", name: "Cutting" }];
  if (url.pathname.endsWith("cutting-batch-progress")) data = { items: batches.map(b => ({ ...b, remaining_quantity: b.planned_quantity, passed_quantity: 0, editable: true, quantity_editable: true })) };
  if (url.pathname === "/api/bundles") data = { rows: [{id:1,bundle_no:'B-1',quantity:60,production_batch_id:180,cutting_record_id:1}, {id:2,bundle_no:'B-2',quantity:60,production_batch_id:180,cutting_record_id:1}, {id:3,bundle_no:'B-3',quantity:40,production_batch_id:186,cutting_record_id:2}, {id:4,bundle_no:'B-4',quantity:40,production_batch_id:186,cutting_record_id:2}] };
  res.end(JSON.stringify(data));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, channel: process.platform === "win32" ? "chrome" : undefined });
try {
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 for(const lang of ['en','ru','uz']){
  await page.goto(`${base}/cutting?lang=${lang}`);
  await page.getByText('B-1',{exact:true}).waitFor();
  const buttons=page.getByRole('button').filter({hasText:new RegExp('^'+messages[lang]['common.print']+' — ')});
  assert.equal(await buttons.count(),2);
  assert.match(await buttons.nth(0).innerText(),/0321-01/);
  assert.match(await buttons.nth(1).innerText(),/0321-02/);
  await buttons.nth(0).click();await buttons.nth(1).click();
  assert.deepEqual(await page.evaluate(()=>window.printedUrls),['/api/bundles/label-sheet/by-ids?ids=1%2C2','/api/bundles/label-sheet/by-ids?ids=3%2C4']);
 }
 assert.deepEqual(writes,[]);assert.deepEqual(errors,[]);
 console.log('PASS: real Cutting page prints only the selected batch in EN/RU/UZ.');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
