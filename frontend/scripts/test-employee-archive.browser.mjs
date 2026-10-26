import assert from "node:assert/strict";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const messages = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, Object.fromEntries(runtimeMessages(lang))]));
const stubs = {
  "next/navigation": "export const usePathname=()=>location.pathname;",
  "next/link": "import React from 'react';export default function Link({children,...p}){return <a {...p}>{children}</a>}",
};
const output = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';
import Page from './src/app/(app)/hr/employees/page';import{LangProvider}from'./src/lib/i18n';
localStorage.setItem('erp_lang',new URLSearchParams(location.search).get('lang')||'en');
createRoot(document.getElementById('root')).render(<LangProvider><Page/></LangProvider>);`, loader: "tsx", resolveDir: root },
  bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
    b.onResolve({ filter: /^next\// }, args => ({ path: args.path, namespace: "fixture" }));
    b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: stubs[args.path], loader: "tsx", resolveDir: root }));
  } }] });
let archived = false, fail = false, allowed = true;
const writes = [];
const employee = { id: 1, full_name: "Fixture Employee", factory_code: "BST", status: "active", hr_profile_json: { payroll_report_group: true } };
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://fixture");
  if (url.pathname === "/fixture.js") { res.setHeader("Content-Type", "text/javascript"); res.end(output.outputFiles[0].text); return; }
  if (!url.pathname.startsWith("/api/")) { res.setHeader("Content-Type", "text/html"); res.end('<html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><div id="root"></div><script src="/fixture.js"></script></html>'); return; }
  res.setHeader("Content-Type", "application/json");
  if (req.method === "POST") {
    writes.push(url.pathname);
    if (fail) { res.statusCode = 409; res.end('{"detail":"Fixture rejection"}'); return; }
    archived = true; res.statusCode = 204; res.end(); return;
  }
  if (req.method === "PATCH") {
    let raw = ""; for await (const part of req) raw += part;
    assert.equal(JSON.parse(raw).hr_profile_json.payroll_report_group, true);
    archived = false; res.end("{}"); return;
  }
  if (url.pathname === "/api/auth/me") { res.end(JSON.stringify({ id: 55, permissions: allowed ? ["payroll.manage"] : ["payroll.view"] })); return; }
  if (url.pathname === "/api/employees") {
    const include = url.searchParams.has("include_archived");
    const rows = archived && !include ? [] : [{ ...employee, status: archived ? "archived" : "active" }];
    res.end(JSON.stringify({ rows, total: rows.length, page: 1, page_size: 50, search: "", include_archived: include, active_total: archived ? 0 : 1 })); return;
  }
  res.end(url.pathname.endsWith("options") ? '{"rows":[]}' : "[]");
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true, channel: process.platform === "win32" ? "chrome" : undefined });
try {
  for (const lang of ["en", "ru", "uz"]) {
    archived = false; fail = false; allowed = true;
    const page = await browser.newPage({ viewport: { width: lang === "uz" ? 390 : 1400, height: 900 } });
    const errors = []; page.on("pageerror", error => errors.push(error.message));
    const t = key => messages[lang][`page.hrEmployees.${key}`];
    await page.goto(`${base}/payroll/employees?lang=${lang}`);
    const remove = page.getByRole("button", { name: t("delete"), exact: true });
    await remove.click();
    await page.getByText(t("archiveConfirm").replace("{name}", employee.full_name), { exact: true }).waitFor();
    const before = writes.length;
    await page.getByRole("button", { name: messages[lang]["common.cancel"], exact: true }).last().click();
    assert.equal(writes.length, before);
    await remove.click(); fail = true;
    await page.getByRole("button", { name: t("archive"), exact: true }).click();
    await page.getByRole("alert").filter({ hasText: t("archiveFailed") }).waitFor();
    fail = false;
    await page.getByRole("button", { name: t("archive"), exact: true }).click();
    await page.getByRole("checkbox", { name: t("showArchived") }).check();
    await page.getByText(t("archived"), { exact: true }).waitFor();
    assert.equal(await remove.count(), 0);
    await page.getByRole("button", { name: t("openProfile"), exact: true }).click();
    await page.getByLabel(t("employmentStatus"), { exact: true }).selectOption("active");
    await page.getByRole("button", { name: t("save"), exact: true }).click();
    await page.getByRole("checkbox", { name: t("showArchived") }).uncheck();
    await remove.waitFor();
    assert.deepEqual(errors, []);
    await page.close();
  }
  allowed = false;
  const page = await browser.newPage(); await page.goto(`${base}/payroll/employees?lang=en`);
  await page.getByRole("button", { name: "Open profile", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Delete employee", exact: true }).count(), 0);
  console.log("PASS: employee archive permission, cancel, failure/retry, history notice, hidden archived list and restoration in EN/RU/UZ.");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
