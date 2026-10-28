// Real React pages with disposable API fixtures; never connects to production.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const out = path.resolve(root, "../outputs/browser");
fs.mkdirSync(out, { recursive: true });
const dictionaries = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, Object.fromEntries(runtimeMessages(lang))]));
const mocks = {
  "@/lib/i18n": `const dict=${JSON.stringify(dictionaries)};export const useT=()=>{const lang=new URLSearchParams(location.search).get('lang')||'en';return{lang,t:(key,args={})=>{let text=dict[lang][key]||key;for(const[k,v]of Object.entries(args))text=text.replaceAll('{'+k+'}',String(v));return text;}}};`,
  "@/lib/auth": `const me={permissions:['*'],factory_code:'MIL'};export const useMe=()=>({me});export const can=()=>true;`,
  "@/components/DialogProvider": `export const useDialogs=()=>({ask:async()=>false});`,
  "next/navigation": `const params=new URLSearchParams(location.search);export const useSearchParams=()=>params;export const usePathname=()=>location.pathname;export const useRouter=()=>({push:()=>{}});`,
  "next/link": `import React from 'react';export default function Link({children,...props}){return React.createElement('a',props,children)}`,
  "@/lib/api": `export const fetchResponse=fetch;export const fetcher=async url=>{const r=await fetch(url);if(!r.ok)throw Error('Fixture request failed');return r.json()};const write=async(method,url,body)=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('Fixture write failed');return r.json()};export const api={get:fetcher,post:(u,b)=>write('POST',u,b),patch:(u,b)=>write('PATCH',u,b)};`,
};
const built = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import Passport from './src/app/(app)/cutting-passports/page';import Employees from './src/app/(app)/hr/employees/page';const Page=location.pathname==='/employees'?Employees:Passport;createRoot(document.getElementById('root')).render(<Page/>);`, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
  b.onResolve({ filter: /^(?:@\/lib\/(?:api|auth|i18n)|@\/components\/DialogProvider|next\/(?:link|navigation))$/ }, args => ({ path: args.path, namespace: "fixture" }));
  b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: mocks[args.path], loader: "js", resolveDir: root }));
} }] });
const sizes = ["44", "46", "48", "50", "52"];
const material = { pieces: 100, planned_kg: 80, total_layers: 10, layer_weight_kg: 2, fabric_width_m: 2, lay_length_m: 4, gramage: .2, size_range: '44-52', meter_mode: false };
let passport = { id: 1, passport_no: 'TEST', date: '2026-10-19T00:00:00Z', production_order_id: 1, size_range: '44-52', materials: [{ ...material, stock_batch_id: 1, fabric_type: 'Cotton A' }, { ...material, stock_batch_id: 2, fabric_type: 'Cotton B' }] };
const writes = [], requests = [];
let failExport = false;
const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, 'http://local');
  if (!u.pathname.startsWith('/api/')) { res.setHeader('Content-Type', 'text/html'); res.end(`<html><body><div id="root"></div><script>${built.outputFiles[0].text}</script></body></html>`); return; }
  requests.push(u);
  if (req.method === 'PATCH') {
    let raw = ''; for await (const part of req) raw += part;
    const body = JSON.parse(raw); writes.push(body); passport = { ...passport, ...body }; res.end(JSON.stringify(passport)); return;
  }
  if (u.pathname === '/api/employees/export.xlsx') {
    res.statusCode = failExport ? 503 : 200;
    res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    res.end(failExport ? 'Failed' : fs.readFileSync('scripts/fixtures/cutting-passports.xlsx')); return;
  }
  let data = [];
  if (u.pathname === '/api/cutting-passports/1') data = passport;
  else if (u.pathname === '/api/cutting-passports') data = [passport];
  else if (u.pathname === '/api/cutting-passports/material-defaults') data = { sizes, size_range: '44-52' };
  else if (u.pathname === '/api/production-orders') data = [{ id: 1, order_no: 'TEST-ORDER' }];
  else if (u.pathname === '/api/employees') data = { rows: [], total: 121, active_total: 121, inactive_total: 0, page: 1, page_size: 50, has_more: true, search: u.searchParams.get('search') || '' };
  res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(data));
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  for (const lang of ['en', 'ru', 'uz']) {
    passport.materials.forEach(row => { row.size_range = '44-52'; });
    await page.goto(`${base}/passports?passport_id=1&lang=${lang}`);
    const selectors = page.locator('form select').filter({ has: page.locator('option[value="44-52"]') });
    await selectors.nth(1).waitFor();
    assert.equal(await selectors.count(), 2);
    await selectors.nth(1).selectOption(sizes.join(', ') + ' ×2');
    assert.equal(await selectors.nth(0).inputValue(), '44-52');
    assert.equal(await selectors.nth(1).inputValue(), sizes.join(', ') + ' ×2');
    await page.screenshot({ path: path.join(out, `fabric-sizes-${lang}.png`), fullPage: true });
    await page.getByRole('button', { name: dictionaries[lang]['common.save'], exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('form'));
    assert.deepEqual(writes.at(-1).materials.map(row => row.size_range), ['44-52', sizes.join(', ') + ' ×2']);
    await page.reload(); await selectors.nth(1).waitFor();
    assert.equal(await selectors.nth(1).inputValue(), sizes.join(', ') + ' ×2');
    await selectors.nth(0).selectOption('46');
    assert.equal(await selectors.nth(1).inputValue(), sizes.join(', ') + ' ×2');
    await page.goto(`${base}/employees?lang=${lang}`);
    await page.getByPlaceholder(dictionaries[lang]['page.hrEmployees.search']).fill('Ada & 01');
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: dictionaries[lang]['employeeExport.download'], exact: true }).click();
    assert.equal((await download).suggestedFilename(), 'employees.xlsx');
    assert.ok(requests.some(u => u.pathname.endsWith('/employees/export.xlsx') && u.searchParams.get('search') === 'Ada & 01' && u.searchParams.get('lang') === lang));
  }
  failExport = true;
  await page.getByRole('button', { name: dictionaries.uz['employeeExport.download'], exact: true }).click();
  await page.getByRole('alert').waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS: independent fabric selectors, save/reopen, all locales, employee download filters and failure handling. No production writes.');
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
