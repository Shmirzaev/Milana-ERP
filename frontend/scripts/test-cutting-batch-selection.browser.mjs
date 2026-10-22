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
  "@/lib/api": `export const fetcher=async url=>{const r=await fetch(url);if(!r.ok)throw Error('Fixture rejection');return r.json()};async function write(method,url,body){const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('Fixture rejection');return r.json()}export const api={get:fetcher,post:(u,b)=>write('POST',u,b),patch:(u,b)=>write('PATCH',u,b),put:(u,b)=>write('PUT',u,b),del:u=>write('DELETE',u)};`,
};
const bundle = await build({ stdin: { resolveDir: root, loader: "tsx", contents: `
import React from 'react';import{createRoot}from'react-dom/client';
import Page from './src/app/(app)/work-orders/[id]/cutting/page';
import{LangProvider}from'./src/lib/i18n';import{DialogProvider}from'./src/components/DialogProvider';
localStorage.setItem('erp_lang',new URLSearchParams(location.search).get('lang')||'en');
createRoot(document.getElementById('root')).render(<LangProvider><DialogProvider><Page/></DialogProvider></LangProvider>);` },
  bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
    b.onResolve({ filter: /^(?:@\/|next\/)/ }, args => args.path in stubs ? { path: args.path, namespace: "fixture" } : undefined);
    b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: stubs[args.path], loader: "tsx", resolveDir: root }));
  } }],
});
const batches = [{ id: 180, batch_no: "0321-01", name: "Nastil 1", batch_index: 1, planned_quantity: 486 },
  { id: 186, batch_no: "0321-02", name: "Extra batch 2", batch_index: 2, planned_quantity: 0 }];
let writes = [], releasePatch, rejectPatch = false;
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
    if (req.method === "PATCH") {
      await new Promise(resolve => { releasePatch = resolve; });
      if (rejectPatch) { res.statusCode = 409; res.end("{}"); return; }
    }
    res.end(JSON.stringify({ id: 319, bundles: [] })); return;
  }
  let data = [];
  if (url.pathname === "/api/work-orders/1260") data = { id: 1260, production_order_id: 321, operation: "cutting", status: "in_progress", department_id: 1, planned_output_qty: 600, passed_qty: 0 };
  if (url.pathname === "/api/production-orders/321") data = { id: 321, production_no: "PO-0296", source_type: "standard", planned_quantity: 600, model_id: 1, batches, items: [48, 50, 52, 54, 56, 58].map(size => ({ color: "white", size: String(size), planned_quantity: 81 })), materials: [] };
  if (url.pathname === "/api/models/1") data = { id: 1, bom: [] };
  if (url.pathname === "/api/departments") data = [{ id: 1, code: "CUT", name: "Cutting" }];
  if (url.pathname.endsWith("cutting-batch-progress")) data = { items: batches.map(b => ({ ...b, remaining_quantity: b.planned_quantity, passed_quantity: 0, editable: true, quantity_editable: true })) };
  if (url.pathname === "/api/bundles") data = { rows: [] };
  res.end(JSON.stringify(data));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const page = await browser.newPage();
  const errors = []; page.on("pageerror", e => errors.push(e.message));
  for (const lang of ["en", "ru", "uz"]) {
    const t = key => messages[lang][key];
    await page.setViewportSize(lang === "en" ? { width: 1366, height: 900 } : { width: 390, height: 844 });
    await page.goto(`${base}/work-orders/1260/cutting?lang=${lang}`);
    const form = page.locator("form");
    const select = form.locator("select").filter({ has: page.locator('option[value="180"]') });
    await select.waitFor();
    await select.selectOption("186");
    const row = page.locator("tbody tr").filter({ hasText: "0321-01" }).first();
    await row.getByRole("button", { name: t("common.edit"), exact: true }).click();
    const saveOutput = form.getByRole("button", { name: t("btn.saveCreateBundles"), exact: true });
    assert.equal(await saveOutput.isDisabled(), true, "Output is blocked during an unfinished batch edit");
    writes = []; releasePatch = undefined;
    await row.getByRole("button", { name: t("btn.save"), exact: true }).click();
    await page.waitForFunction(() => document.querySelector("form button.btn-primary")?.disabled);
    while (!releasePatch) await new Promise(resolve => setImmediate(resolve));
    assert.equal(await saveOutput.isDisabled(), true, "Output remains blocked while the plan save is pending");
    releasePatch();
    await page.waitForFunction(() => document.querySelector('form select')?.value === '180');
    assert.equal(writes[0].path, "/api/work-orders/1260/batches/180");
    await form.getByRole("status").filter({ hasText: "0321-01" }).waitFor();
    // The real page prepares six size bundles, matching the affected order's shape.
    const outputLabel = form.locator("label").filter({ hasText: t("field.cutPieces") });
    const output = outputLabel.locator("..").locator("input");
    await output.fill("486");
    await saveOutput.click();
    const modal = page.locator(".fixed.inset-0");
    await modal.getByText(/486/).waitFor();
    assert.match(await modal.innerText(), /0321-01/);
    assert.doesNotMatch(await modal.innerText(), /0321-02/);
    assert.equal(writes.filter(w => w.method === "POST").length, 0, "Confirmation must precede the write");
    await modal.getByRole("button", { name: t("common.cancel"), exact: true }).click();
    assert.equal(await output.inputValue(), "486", "Cancelling preserves the operator's draft");
    await saveOutput.click();
    await modal.getByRole("button", { name: t("common.confirm"), exact: true }).click();
    await page.waitForFunction(() => !document.querySelector("form button.btn-primary")?.disabled);
    const post = writes.find(w => w.method === "POST");
    assert.equal(post.path, "/api/cutting/records");
    assert.equal(post.body.production_batch_id, 180);
    assert.equal(post.body.passed_pieces, 486);
    assert.equal(post.body.bundles.length, 6);
    assert.equal(post.body.bundles.reduce((sum, b) => sum + b.quantity * b.count, 0), 486);
    // A rejected plan edit must never silently select its batch.
    await select.selectOption("186");
    await row.getByRole("button", { name: t("common.edit"), exact: true }).click();
    rejectPatch = true; releasePatch = undefined;
    await row.getByRole("button", { name: t("btn.save"), exact: true }).click();
    while (!releasePatch) await new Promise(resolve => setImmediate(resolve));
    releasePatch();
    await page.getByText("Fixture rejection", { exact: true }).waitFor();
    assert.equal(await select.inputValue(), "186");
    assert.equal(await saveOutput.isDisabled(), true);
    rejectPatch = false;
  }
  assert.deepEqual(errors, []);
  console.log("Cutting batch edit → output binding, pending/failed edit guards, exact batch/quantity confirmation, cancel/retry and EN/RU/UZ desktop/mobile passed.");
} finally { await browser.close(); server.close(); }
