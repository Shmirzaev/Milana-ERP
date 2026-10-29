// Real Sewing form: cancelled history, later-batch choice, exact assignment payload.
import assert from "node:assert/strict";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const stubs = {
  "next/navigation": `export const useParams=()=>({id:'1347'});`,
  "next/link": `import React from 'react';export default function Link(p){return <a {...p}/>}`,
  "@/lib/auth": `export const useMe=()=>({me:{id:1,permissions:['*']}});export const can=()=>true;`,
  "@/components/sewing/BandOrder": `export default function Band(){return null}`,
  "@/components/WorkOrderProductInfo": `export default function Product(){return null}`,
  "@/components/PageHeader": `export default function Header(){return null}`,
  "@/lib/api": `export const fetcher=async u=>(await fetch(u)).json();export const api={post:async(u,b)=>{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});if(!r.ok)throw Error('Fixture rejection');return r.json()}};`,
};
const bundled = await build({ stdin: { resolveDir: root, loader: "tsx", contents: `
import React from 'react';import{createRoot}from'react-dom/client';
import Page from './src/app/(app)/work-orders/[id]/sewing/page';
import{LangProvider}from'./src/lib/i18n';import{DialogProvider}from'./src/components/DialogProvider';
localStorage.setItem('erp_lang',new URLSearchParams(location.search).get('lang')||'en');
createRoot(document.getElementById('root')).render(<LangProvider><DialogProvider><Page/></DialogProvider></LangProvider>);` },
  bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
    b.onResolve({ filter: /^(?:@\/|next\/)/ }, a => a.path in stubs ? { path: a.path, namespace: "fixture" } : undefined);
    b.onLoad({ filter: /.*/, namespace: "fixture" }, a => ({ contents: stubs[a.path], loader: "tsx", resolveDir: root }));
  } }],
});
let factory = "MIL", writes = [], records = [], assignments = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname === "/fixture.js") { res.setHeader("Content-Type", "text/javascript"); res.end(bundled.outputFiles[0].text); return; }
  if (!url.pathname.startsWith("/api/")) {
    res.setHeader("Content-Type", "text/html");
    res.end('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>'); return;
  }
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") {
    let raw = ""; for await (const part of req) raw += part;
    const body = JSON.parse(raw); writes.push(body);
    records.push({ ...body, id: records.length + 1, correction_version: 0, created_at: new Date().toISOString(), size_quantities: [], locked_reason: null });
    res.end(JSON.stringify({ id: records.length })); return;
  }
  let data = [];
  if (url.pathname === "/api/work-orders/1347") data = { id: 1347, production_order_id: 346, operation: "sewing", status: "in_progress" };
  if (url.pathname === "/api/production-orders/346") data = { id: 346, production_no: "PO-0307", model_id: 1,
    batches: [1, 2, 3, 4].map(id => ({ id, batch_index: id, name: `Nastil ${id}`, planned_quantity: 128 })) };
  if (url.pathname === "/api/models/1") data = { id: 1 };
  if (url.pathname === "/api/sewing-flows") data = [1, 2, 3].map(id => ({ id, name: `${factory} line ${id}`, code: `${factory}-${id}` }));
  if (url.pathname.endsWith("assignments")) data = assignments;
  if (url.pathname.endsWith("sewing-batch-progress")) data = { items: [1, 2, 3].map(id => ({ id })) };
  if (url.pathname.endsWith("sewing-records")) data = records;
  res.end(JSON.stringify(data));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true, channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const page = await browser.newPage(), errors = [];
  page.on("pageerror", e => errors.push(e.message));
  for (factory of ["MIL", "BST", "ECO"]) for (const lang of ["en", "ru", "uz"]) {
    const t = key => runtimeMessages(lang).get(key);
    writes = []; records = [];
    assignments = [
      { id: 85, production_batch_id: 1, sewing_flow_id: 1, quantity: 128, completed_qty: 0, status: "cancelled" },
      { id: 87, production_batch_id: 1, sewing_flow_id: 1, quantity: 128, completed_qty: 128, status: "completed" },
      { id: 120, production_batch_id: 2, sewing_flow_id: 2, quantity: 128, completed_qty: 0, status: "in_progress" },
    ];
    await page.setViewportSize(lang === "en" ? { width: 1366, height: 900 } : { width: 390, height: 844 });
    const url = `http://127.0.0.1:${server.address().port}/work-orders/1347/sewing?lang=${lang}`;
    await page.goto(url);
    const form = page.locator("form").first(), batch = form.locator("select").nth(0), line = form.locator("select").nth(1);
    await page.waitForFunction(() => document.querySelector('option[value="assignment:120"]'));
    await page.waitForFunction(() => document.querySelector('form select')?.value === "2");
    assert.equal(await batch.locator('option[value="4"]').count(), 0, "A Nastil owned by another work order is not selectable");
    assert.equal(await line.locator('option[value="assignment:85"]').count(), 0);
    assert.equal(await line.inputValue(), "assignment:120");
    assert.equal(await batch.isEnabled(), true);
    await batch.selectOption("3");
    await page.waitForFunction(() => document.querySelectorAll('form select')[1]?.value === "");
    assert.equal(await form.locator('a[href="/sewing/flows"]').innerText(), t("nav.sewingFlows"));
    assert.equal(writes.length, 0);
    // Assigning a line elsewhere makes the exact batch selectable on refresh.
    assignments.push({ id: 121, production_batch_id: 3, sewing_flow_id: 3, quantity: 128, completed_qty: 0, status: "planned" });
    await page.goto(url);
    await page.waitForFunction(() => document.querySelector('option[value="assignment:121"]'));
    await batch.selectOption("3");
    assert.equal(await line.inputValue(), "assignment:121");
    await form.locator('input[type="number"]').nth(0).fill("128");
    await form.locator('input[type="number"]').nth(1).fill("128");
    await form.locator('button[type="submit"], button:not([type])').click();
    await page.waitForFunction(() => document.querySelector('#sewing-record-input')?.value === "");
    assert.equal(writes.length, 1);
    assert.equal(writes[0].production_batch_id, 3);
    assert.equal(writes[0].sewing_assignment_id, 121);
    assert.equal(writes[0].passed_qty, 128);
  }
  assert.deepEqual(errors, []);
  console.log("Later Nastil form passed: MIL/BST/ECO, EN/RU/UZ, phone/desktop, cancelled history, assignment navigation and exact save.");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
