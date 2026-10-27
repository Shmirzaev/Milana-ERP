// Real receiving form with disposable HTTP fixtures; no production data writes.
import assert from "node:assert/strict";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const messages = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, Object.fromEntries(runtimeMessages(lang))]));
const stubs = {
  "next/navigation": "export const useSearchParams=()=>new URLSearchParams(location.search);",
  "@/lib/api": `export const fetcher=async u=>(await fetch(u)).json();export const api={post:async(u,b)=>{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});if(!r.ok)throw Error('Fixture rejection');return r.json()}};`,
};
const bundle = await build({ stdin: { resolveDir: root, loader: "tsx", contents: `
import React from 'react';import{createRoot}from'react-dom/client';
import Page from './src/app/(app)/inventory/receive/page';import{LangProvider}from'./src/lib/i18n';
localStorage.setItem('erp_lang',new URLSearchParams(location.search).get('lang')||'en');
createRoot(document.getElementById('root')).render(<LangProvider><Page/></LangProvider>);` },
  bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
    b.onResolve({ filter: /^(?:@\/|next\/)/ }, args => args.path in stubs ? { path: args.path, namespace: "fixture" } : undefined);
    b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: stubs[args.path], loader: "tsx", resolveDir: root }));
  } }],
});
const writes = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname === "/fixture.js") { res.setHeader("Content-Type", "text/javascript"); res.end(bundle.outputFiles[0].text); return; }
  if (!url.pathname.startsWith("/api/")) {
    res.setHeader("Content-Type", "text/html");
    res.end('<html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><div id="root"></div><script src="/fixture.js"></script></html>'); return;
  }
  res.setHeader("Content-Type", "application/json");
  if (req.method !== "GET") {
    let raw = ""; for await (const part of req) raw += part;
    writes.push({ path: url.pathname, body: JSON.parse(raw) }); res.statusCode = 201; res.end('{"id":1}'); return;
  }
  let data = [];
  if (url.pathname === "/api/inventory/items") data = [{ id: 1, name: "Kg fabric", category: "fabric", unit: "kg" }, { id: 2, name: "Meter fabric", category: "fabric", unit: "M" }];
  if (url.pathname === "/api/inventory/warehouses") data = [{ id: 1, name: "Fabric warehouse", type: "fabric_storage" }];
  res.end(JSON.stringify(data));
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, channel: process.platform === "win32" ? "chrome" : undefined });
try {
  for (const lang of ["en", "ru", "uz"]) {
    const page = await browser.newPage({ viewport: { width: lang === "uz" ? 390 : 1400, height: 900 } });
    const errors = []; page.on("pageerror", e => errors.push(e.message));
    await page.goto(`${base}/inventory/receive?lang=${lang}`);
    const form = page.locator("form").first();
    const field = key => form.locator("label").filter({ hasText: new RegExp(`^${messages[lang][key].replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`) }).locator("..").locator("input").first();
    await form.locator("select").first().selectOption("1");
    await page.locator("#fabric-weight-entry").selectOption("length");
    assert.equal(await field("field.unit").inputValue(), "m");
    assert.equal(await form.locator("fieldset").count(), 0);
    await field("fabricRollEntry.totalMeters").fill("123.45");
    await field("field.pieceCount").fill("3");
    await field("field.batch").fill(`METERS-${lang}`);
    await form.locator("select").filter({ has: page.locator('option[value="1"]').filter({ hasText: "Fabric warehouse" }) }).selectOption("1");
    const before = writes.length;
    await Promise.all([
      page.waitForResponse(r => r.url().endsWith("/api/inventory/receive") && r.request().method() === "POST"),
      form.locator("button.btn-primary").last().click(),
    ]);
    assert.equal(writes.length, before + 1);
    const body = writes.at(-1).body;
    assert.equal(body.quantity, 123.45); assert.equal(body.unit, "m"); assert.equal(body.piece_count, 3);
    assert.deepEqual(body.roll_weights_kg, []); assert.deepEqual(body.roll_lengths_m, []);
    await form.locator("select").first().selectOption("2");
    assert.equal(await page.locator("#fabric-weight-entry").inputValue(), "length");
    await field("fabricRollEntry.totalMeters").fill("55");
    await page.locator("#fabric-weight-entry").selectOption("total");
    assert.equal(await field("field.unit").inputValue(), "kg");
    assert.equal(await field("fabricRollEntry.totalKg").inputValue(), "");
    await field("field.unit").fill("M");
    assert.equal(await page.locator("#fabric-weight-entry").inputValue(), "length");
    assert.deepEqual(errors, []); await page.close();
  }
  console.log("PASS: actual meter receiving form, payload, unit changes and EN/RU/UZ desktop/phone.");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
