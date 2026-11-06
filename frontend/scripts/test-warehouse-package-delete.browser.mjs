import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium } from "playwright";

const root = process.cwd();
const stubs = {
  "@/lib/auth": `export const useMe=()=>({me:window.testMe}); export const can=me=>me.permissions.includes('storage.packages');`,
  "@/lib/i18n": `export const useT=()=>({lang:document.documentElement.lang});`,
  "@/components/DialogProvider": `export const useDialogs=()=>({ask:async options=>{window.confirmations.push(options.message);return true;}});`,
  "swr": `export const mutate=async predicate=>{window.refreshed=['/api/packages','/api/finished-goods','/api/inbox'].filter(predicate);};`,
};
const bundle = await build({
  stdin: { contents: `import React from 'react';import {createRoot} from 'react-dom/client';import Delete from './src/components/DeleteWarehousePackage';createRoot(document.getElementById('root')).render(<Delete id={41} packageNo="OLD-TEST-9"/>);`, resolveDir: root, loader: "tsx" },
  bundle: true, write: false, format: "iife", jsx: "automatic",
  plugins: [{ name: "fixtures", setup(b) {
    b.onResolve({ filter: /^(@\/|swr$)/ }, a => a.path in stubs ? { path: a.path, namespace: "fixtures" } : undefined);
    b.onLoad({ filter: /.*/, namespace: "fixtures" }, a => ({ contents: stubs[a.path], loader: "tsx", resolveDir: root }));
  } }],
});
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let attempts = 0;
  await page.route("http://localhost:3199/**", async route => {
    if (route.request().method() === "DELETE") {
      assert.ok(route.request().url().endsWith("/api/packages/warehouse/41"));
      attempts++;
      return route.fulfill({ status: attempts === 1 ? 409 : 200, contentType: "application/json",
        body: JSON.stringify(attempts === 1 ? { detail: "Package is linked to a shipment and cannot be deleted" } : { deleted_count: 1 }) });
    }
    return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
  });
  for (const [lang, expected] of [["en", "linked to a shipment"], ["ru", "добавлена в отгрузку"], ["uz", "jo‘natmaga qo‘shilgan"]]) {
    await page.goto("http://localhost:3199/");
    await page.evaluate(lang => {
      document.documentElement.lang = lang;
      window.testMe = { permissions: ["storage.packages"] };
      window.confirmations = []; window.refreshed = [];
      localStorage.setItem("token", "fixture-token");
    }, lang);
    attempts = 0;
    await page.addScriptTag({ content: bundle.outputFiles[0].text });
    await page.getByRole("button").click();
    await page.getByRole("alert").waitFor();
    assert.ok((await page.getByRole("alert").innerText()).includes(expected));
    assert.equal(await page.getByRole("button").isDisabled(), false);
    await page.getByRole("button").click();
    await page.waitForFunction(() => window.refreshed.length === 3);
    assert.equal(await page.getByRole("alert").count(), 0);
    assert.equal(attempts, 2);
    const confirmations = await page.evaluate(() => window.confirmations);
    assert.ok(confirmations.every(message => message.includes("OLD-TEST-9")));
    assert.ok(confirmations.every(message => /history|инвентаризации|Inventarizatsiya/.test(message)));
  }
  await page.goto("http://localhost:3199/");
  await page.evaluate(() => { document.documentElement.lang = "en"; window.testMe = { permissions: [] }; });
  await page.addScriptTag({ content: bundle.outputFiles[0].text });
  assert.equal(await page.getByRole("button").count(), 0);
  assert.deepEqual(errors, []);
  console.log("Warehouse delete: EN/RU/UZ specific errors, confirmation, retry, refresh and permission visibility passed.");
} finally { await browser.close(); }
