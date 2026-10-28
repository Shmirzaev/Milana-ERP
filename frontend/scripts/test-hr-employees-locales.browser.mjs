// Real employee pages, language provider and HR components; disposable HTTP fixtures only.
import assert from "node:assert/strict";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const messages = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, Object.fromEntries(runtimeMessages(lang))]));
const mocks = {
  "next/navigation": `export const usePathname=()=>location.pathname;`,
  "next/link": `import React from 'react';export default function Link({children,...props}){return React.createElement('a',props,children);}`,
  "@/lib/api": `export const fetchResponse=fetch;export const fetcher=async url=>{const r=await fetch(url);if(!r.ok)throw Error('Failed to fetch');return r.json()};const write=async(method,url,body)=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('Failed to fetch');return r.json()};export const api={post:(u,b)=>write('POST',u,b),patch:(u,b)=>write('PATCH',u,b)};`,
};
const entry = `import React from 'react';import{createRoot}from'react-dom/client';
import Employees from './src/app/(app)/hr/employees/page';
import Admin from './src/app/(app)/admin/employees/page';
import Payroll from './src/app/(app)/payroll/employees/page';
import{HrWorkspaceNav}from'./src/components/hr/HrUi';
import{LangProvider,useT}from'./src/lib/i18n';
localStorage.setItem('erp_lang',new URLSearchParams(location.search).get('lang')||'en');
function App(){const{setLang}=useT();const Page=location.pathname==='/admin/employees'?Admin:location.pathname==='/payroll/employees'?Payroll:Employees;return <><aside>{['en','ru','uz'].map(l=><button key={l} data-lang={l} onClick={()=>setLang(l)}>{l}</button>)}</aside>{location.pathname.startsWith('/hr')&&<HrWorkspaceNav/>}<Page/></>}
createRoot(document.getElementById('root')).render(<LangProvider><App/></LangProvider>);`;
const bundle = await build({ stdin: { contents: entry, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
  b.onResolve({ filter: /^(?:@\/lib\/api|next\/(?:link|navigation))$/ }, args => ({ path: args.path, namespace: "fixture" }));
  b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: mocks[args.path], loader: "js", resolveDir: root }));
} }] });
const employees = ["active", "inactive", "on_leave", "terminated"].map((status, index) => ({
  id: index + 1, employee_no: String(index + 1).padStart(4, "0"), full_name: `Fixture ${index + 1}`,
  department_id: null, position: "Operator", phone: null, salary: null, status,
  joined_at: "2026-10-20T00:00:00Z", manager_employee_id: 8, manager_name: "Fixture Manager",
  hr_position_id: null, hr_profile_json: { gender: "female", company: "Fixture factory", bank_details: "Original bank" },
}));
const writes = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://local");
  if (url.pathname === "/fixture.js") { res.setHeader("Content-Type", "text/javascript"); res.end(bundle.outputFiles[0].text); return; }
  if (!url.pathname.startsWith("/api/")) {
    res.setHeader("Content-Type", "text/html");
    res.end('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script src="/fixture.js"></script></body></html>'); return;
  }
  res.setHeader("Content-Type", "application/json");
  if (["POST", "PATCH"].includes(req.method)) {
    let raw = ""; for await (const part of req) raw += part;
    writes.push({ method: req.method, url: url.pathname, body: JSON.parse(raw) });
    res.end("{}"); return;
  }
  if (url.pathname === "/api/employees") {
    const search = url.searchParams.get("search") || "";
    if (search === "error") { res.statusCode = 503; res.end("{}"); return; }
    const rows = search === "empty" ? [] : employees;
    // Make the translated loading state observable without contacting a real API.
    await new Promise(resolve => setTimeout(resolve, 150));
    res.end(JSON.stringify({ rows, total: rows.length, page: Number(url.searchParams.get("page")), page_size: 50,
      has_more: false, active_total: 1, inactive_total: 3, profile_coverage_percent: 25, search })); return;
  }
  if (url.pathname.endsWith("manager-options")) { res.end(JSON.stringify({ rows: [{ id: 8, full_name: "Fixture Manager" }], has_more: false })); return; }
  if (url.pathname.endsWith("position-options")) { res.end(JSON.stringify({ rows: [], has_more: false })); return; }
  res.end("[]");
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const text = (lang, key) => messages[lang][`page.hrEmployees.${key}`];
  const sections = { Personal: ["photo_url", "date_of_birth", "gender", "email", "address", "emergency_contact", "nationality"],
    Employment: ["company", "branch", "section", "grade_level", "employment_type", "probation_end", "work_schedule", "shift", "workplace", "scheduled_daily_hours"],
    Financial: ["rate_type", "bonus_scheme", "bank_details", "payroll_id"] };
  for (const route of ["/hr/employees", "/admin/employees", "/payroll/employees"]) {
    for (const lang of ["en", "ru", "uz"]) {
      await page.goto(`${base}${route}?lang=${lang}`);
      await page.getByRole("heading", { name: text(lang, "title"), exact: true }).waitFor();
      await page.getByRole("button", { name: text(lang, "openProfile"), exact: true }).first().waitFor();
      assert.equal(await page.locator("tbody tr").count(), 4);
      for (const [index, status] of ["active", "inactive", "on_leave", "terminated"].entries()) {
        assert.equal(await page.locator("tbody tr").nth(index).locator(".badge").innerText(), text(lang, status));
      }
      assert.equal(await page.getByText(text(lang, "unassigned"), { exact: true }).count(), 4);
      if (route.startsWith("/hr")) {
        for (const key of Object.keys(messages[lang]).filter(key => key.startsWith("hrWorkspace.") && !["loading", "empty", "loadError", "navigation"].some(suffix => key.endsWith(`.${suffix}`)))) {
          await page.getByRole("navigation").getByRole("link", { name: messages[lang][key], exact: true }).waitFor();
        }
      }
      await page.getByRole("button", { name: text(lang, "openProfile"), exact: true }).first().click();
      await page.getByRole("heading", { name: text(lang, "profileTitle").replace("{name}", "Fixture 1"), exact: true }).waitFor();
      assert.equal(await page.getByLabel(text(lang, "fullName"), { exact: true }).inputValue(), "Fixture 1");
      for (const [section, fields] of Object.entries(sections)) {
        await page.getByRole("button", { name: text(lang, `section${section}`), exact: true }).click();
        for (const field of fields) await page.getByLabel(text(lang, field), { exact: true }).waitFor();
      }
      // Business values and JSON keys stay unchanged when switching language with an unsaved edit.
      await page.getByLabel(text(lang, "bank_details"), { exact: true }).fill("Updated fixture bank");
      const nextLang = lang === "uz" ? "ru" : "uz";
      await page.locator(`[data-lang="${nextLang}"]`).click();
      await page.getByLabel(text(nextLang, "bank_details"), { exact: true }).waitFor();
      assert.equal(await page.getByLabel(text(nextLang, "bank_details"), { exact: true }).inputValue(), "Updated fixture bank");
      await page.getByRole("button", { name: text(nextLang, "save"), exact: true }).click();
      await page.waitForFunction(() => !document.querySelector("form"));
      const saved = writes.at(-1);
      assert.equal(saved.method, "PATCH"); assert.equal(saved.url, "/api/employees/1");
      assert.deepEqual(saved.body.hr_profile_json, { gender: "female", company: "Fixture factory", bank_details: "Updated fixture bank" });
      assert.equal(saved.body.status, "active"); assert.equal(saved.body.manager_employee_id, 8);
      // Creation labels, loading, empty and failed-fetch states are translated as well.
      await page.getByRole("button", { name: text(nextLang, "add"), exact: true }).click();
      await page.getByRole("heading", { name: text(nextLang, "newEmployee"), exact: true }).waitFor();
      await page.getByRole("button", { name: messages[nextLang]["common.cancel"], exact: true }).click();
      const search = page.getByPlaceholder(text(nextLang, "search"));
      await search.fill("empty");
      await page.getByText(messages[nextLang]["hrWorkspace.loading"], { exact: true }).waitFor();
      await page.getByText(messages[nextLang]["hrWorkspace.empty"], { exact: true }).waitFor();
      await search.fill("error");
      await page.getByRole("alert").filter({ hasText: messages[nextLang]["hrWorkspace.loadError"] }).waitFor();
      const visible = await page.locator("body").innerText();
      assert.ok(!visible.includes("page.hrEmployees.") && !visible.includes("hrWorkspace."), "No missing keys may render");
    }
  }
  assert.equal(writes.length, 9);
  assert.deepEqual(errors, []);
  console.log("PASS: HR/Admin/Payroll employee pages in EN/RU/UZ, all profile tabs, statuses, navigation, language changes, save payloads, and loading/empty/error states. All writes use disposable fixtures.");
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
