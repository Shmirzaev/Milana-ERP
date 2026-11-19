// Real Sewing form, saved-record refresh and localized input guidance.
import assert from "node:assert/strict";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const stubs = {
  "next/navigation": `export const useParams=()=>({id:'1069'});`,
  "next/link": `import React from 'react';export default function Link(p){return <a {...p}/>}`,
  "@/lib/auth": `export const useMe=()=>({me:{id:1,permissions:['*']}});export const can=()=>true;`,
  "@/components/sewing/BandOrder": `export default function Band(){return null}`,
  "@/components/WorkOrderProductInfo": `export default function Product(){return null}`,
  "@/components/PageHeader": `export default function Header(){return null}`,
  "@/lib/api": `export const API_TIMEOUT_EVENT='milana:api-timeout';export const fetcher=async url=>{const r=await fetch(url);if(!r.ok)throw Error('Fixture rejection');return r.json()};export const api={post:async(u,b)=>{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});if(!r.ok)throw Error('Fixture rejection');return r.json()}};`,
};
const bundle = await build({ stdin: { resolveDir: root, loader: "tsx", contents: `
import React from 'react';import{createRoot}from'react-dom/client';
import Page from './src/app/(app)/work-orders/[id]/sewing/page';
import{LangProvider}from'./src/lib/i18n';import{DialogProvider}from'./src/components/DialogProvider';
localStorage.setItem('erp_lang',new URLSearchParams(location.search).get('lang')||'en');
createRoot(document.getElementById('root')).render(<LangProvider><DialogProvider><Page/></DialogProvider></LangProvider>);` },
  bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
    b.onResolve({ filter: /^(?:@\/|next\/)/ }, args => args.path in stubs ? { path: args.path, namespace: "fixture" } : undefined);
    b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: stubs[args.path], loader: "tsx", resolveDir: root }));
  } }],
});
let writes = [], records = [];
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
    const body = JSON.parse(raw); writes.push({ path: url.pathname, body });
    records.push({ ...body, id: records.length + 1, correction_version: 0, created_at: new Date().toISOString(), size_quantities: [], locked_reason: null });
    res.end(JSON.stringify({ id: records.length })); return;
  }
  let data = [];
  if (url.pathname === "/api/work-orders/1069") data = { id: 1069, production_order_id: 273, operation: "sewing", status: "in_progress", actual_input_qty: 600 };
  if (url.pathname === "/api/production-orders/273") data = { id: 273, production_no: "PO-0248", model_id: 1, batches: [] };
  if (url.pathname === "/api/models/1") data = { id: 1 };
  if (url.pathname === "/api/sewing-flows") data = [{ id: 1, name: "Oydinoy Mamadaliyeva", code: "BST-BAND-01" }];
  if (url.pathname.endsWith("sewing-batch-progress")) data = { items: [] };
  if (url.pathname.endsWith("sewing-records")) data = records;
  res.end(JSON.stringify(data));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true, channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const page = await browser.newPage();
  const errors = []; page.on("pageerror", e => errors.push(e.message));
  for (const lang of ["en", "ru", "uz"]) {
    const messages = runtimeMessages(lang), t = key => messages.get(key);
    writes = []; records = [];
    await page.setViewportSize(lang === "en" ? { width: 1366, height: 900 } : { width: 390, height: 844 });
    await page.goto(`http://127.0.0.1:${server.address().port}/work-orders/1069/sewing?lang=${lang}`);
    const input = page.getByLabel(t("sewing.recordInput"), { exact: true });
    await input.waitFor();
    assert.equal(await input.getAttribute("aria-describedby"), "sewing-record-input-help");
    assert.equal(await page.locator("#sewing-record-input-help").innerText(), t("sewing.recordInputHelp"));
    assert.equal(writes.length, 0);
    const form = page.locator("form").first();
    await input.fill("495");
    await form.locator('input[type="number"]').nth(1).fill("495");
    await form.locator("select").first().selectOption("flow:1");
    await form.locator('button[type="submit"], button:not([type])').click();
    await page.waitForFunction(() => document.querySelector("#sewing-record-input")?.value === "");
    assert.equal(writes.length, 1);
    assert.equal(writes[0].path, "/api/sewing/records");
    assert.equal(writes[0].body.input_qty, 495);
    assert.equal(writes[0].body.passed_qty, 495);
    assert.equal(writes[0].body.production_batch_id, null);
    await page.locator("tbody tr").filter({ hasText: "Oydinoy Mamadaliyeva" }).waitFor();
    // Input can be registered on an earlier day; output-only entry remains valid.
    await input.fill("0");
    await form.locator('input[type="number"]').nth(1).fill("105");
    await form.locator('button[type="submit"], button:not([type])').click();
    await page.waitForFunction(() => document.querySelector("#sewing-record-input")?.value === "");
    assert.equal(writes.length, 2);
    assert.equal(writes[1].body.input_qty, 0);
    assert.equal(writes[1].body.passed_qty, 105);
  }
  assert.deepEqual(errors, []);
  console.log("Sewing received-input form: EN/RU/UZ, desktop/phone, 495-piece save, history refresh and output-only save passed.");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
