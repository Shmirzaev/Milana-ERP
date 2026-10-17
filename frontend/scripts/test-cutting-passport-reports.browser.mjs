// Actual ERP page and shell, disposable local fixtures only. --serve keeps a review preview open.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { execFileSync } from "node:child_process";
import { build } from "esbuild";
import { chromium } from "playwright";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = process.cwd();
const out = path.resolve(root, "../outputs/passport-preview");
fs.mkdirSync(out, { recursive: true });
const dictionaries = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, Object.fromEntries(runtimeMessages(lang))]));
const mocks = {
  "@/lib/i18n": `const dict=${JSON.stringify(dictionaries)};const params=new URLSearchParams(location.search);export const useT=()=>({lang:params.get('lang')||'en',setLang:lang=>{params.set('lang',lang);location.search=params.toString()},t:(key,args={})=>{let text=dict[params.get('lang')||'en'][key]||key;for(const[k,v]of Object.entries(args))text=text.replaceAll('{'+k+'}',String(v));return text;}});`,
  "@/lib/auth": `const me={id:1,name:'Preview operator',department:'Cutting',department_code:'CUT',role:'Cutting',factory_code:'MIL',available_factories:['MIL'],permissions:new URLSearchParams(location.search).has('denied')?[]:['cutting.records','cutting.bundles']};export const useMe=()=>({me});export const can=(me,...permissions)=>!!me&&permissions.some(p=>me.permissions.includes(p));export const logout=()=>{};`,
  "@/lib/theme": `export const useTheme=()=>({isNight:false,toggleTheme:()=>{}});`,
  "@/components/DialogProvider": `export const useDialogs=()=>({confirm:async()=>false,alert:async()=>{}});`,
  "next/link": `import React from 'react';export default function Link({children,...props}){return React.createElement('a',props,children)}`,
  "next/navigation": `const params=new URLSearchParams(location.search);export const useSearchParams=()=>params;export const usePathname=()=>'/cutting-passports';export const useRouter=()=>({push:url=>{location.href=url}});`,
  "@/lib/api": `export const fetchResponse=fetch;export const fetcher=async url=>{const r=await fetch(url);if(!r.ok)throw Error('Fixture request failed');return r.json()};const write=async(method,url,body)=>{const r=await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error('Fixture write failed');return r.json()};export const api={get:fetcher,post:(u,b)=>write('POST',u,b),patch:(u,b)=>write('PATCH',u,b),delete:()=>{throw Error('Unexpected delete')}};`,
};
const built = await build({ stdin: { contents: `import React from 'react';import{createRoot}from'react-dom/client';import Page from './src/app/(app)/cutting-passports/page';import AppShell from './src/components/AppShell';createRoot(document.getElementById('root')).render(<><div style={{padding:'8px 16px',background:'#efe9d8',textAlign:'center',fontSize:13}}>Local review preview · sample data · production unchanged</div><AppShell><Page/></AppShell></>);`, resolveDir: root, loader: "tsx" }, bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(b) {
  b.onResolve({ filter: /^(?:@\/lib\/(?:api|auth|i18n|theme)|@\/components\/DialogProvider|next\/(?:link|navigation))$/ }, args => ({ path: args.path, namespace: "fixture" }));
  b.onLoad({ filter: /.*/, namespace: "fixture" }, args => ({ contents: mocks[args.path], loader: "js", resolveDir: root }));
} }] });
const css = execFileSync(process.execPath, ["node_modules/tailwindcss/lib/cli.js", "-i", "src/app/globals.css", "--minify"], { encoding: "utf8", maxBuffer: 8 * 1024 * 1024, stdio: ["ignore", "pipe", "pipe"] });
const sample = Array.from({ length: 6 }, (_, index) => ({
  id: index + 1, passport_no: `CP-${String(101 + index).padStart(4, '0')}`, date: `2026-10-${String(12 + index).padStart(2, '0')}T00:00:00Z`,
  created_at: '2026-10-17T00:00:00Z', updated_at: '2026-10-17T00:00:00Z', production_order_id: null,
  operator_id: null, operator_name: 'Aziz', operator_name_manual: 'Aziz', model_code: 'TJ2220', model_name: 'TJ2220', variant: String(6470 + index),
  mold_no: 'TJ-22', size_range: '44, 46, 48, 50, 52', fabric_type: index === 4 ? 'Poplin' : 'Cotton jersey', lot_no: `FAB-${100 + index}`,
  order_no: `PO-0${450 + index}`, has_print: false, meter_mode: index === 4, tepa_pass: index === 5,
  rolls_count: 3 + index, pieces: 300, total_layers: 60, layer_weight_kg: 2.4, planned_kg: 160,
  fabric_width_m: 1.7, lay_length_m: 7.6, gramage: .19, waste_pct: 2, beka_per_piece_kg: .01,
  other_beka_per_piece_kg: 0, scrap_kg: 1, ribana_per_piece_kg: 0, actual_kg: index === 4 ? 460 : 148 + index * 4,
  theoretical_kg: 150, per_piece_weight_kg: .49, actual_kg_per_piece: .50, gross_kg_per_piece: .53,
  total_beka_kg: 3, other_beka_kg: 0, total_ribana_kg: 0, materials: [], notes: '',
}));
let records = structuredClone(sample), writes = [], requests = [], failDashboard = false, failExport = false;
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://local');
  if (url.pathname.startsWith('/branding/')) {
    const file = path.join(root, 'public', url.pathname);
    if (fs.existsSync(file)) { res.setHeader('Content-Type', 'image/svg+xml'); res.end(fs.readFileSync(file)); return; }
  }
  if (url.pathname.startsWith('/api/')) {
    requests.push({ method: req.method, path: url.pathname, query: url.search });
    res.setHeader('Content-Type', 'application/json');
    if (req.method === 'POST' || req.method === 'PATCH') {
      let body = ''; for await (const part of req) body += part;
      const payload = JSON.parse(body); writes.push(payload);
      if (url.pathname.startsWith('/api/cutting-passports')) {
        const record = { ...sample[0], ...payload, id: records.length + 1, materials: [] };
        records.push(record); res.end(JSON.stringify(record)); return;
      }
      res.statusCode = 500; res.end('{}'); return;
    }
    let data = [];
    const rows = records.filter(row => (!url.searchParams.get('date_from') || row.date.slice(0, 10) >= url.searchParams.get('date_from')) && (!url.searchParams.get('date_to') || row.date.slice(0, 10) <= url.searchParams.get('date_to')) && (!url.searchParams.get('q') || row.passport_no.includes(url.searchParams.get('q'))));
    if (url.pathname === '/api/cutting-passports') data = rows;
    else if (url.pathname === '/api/cutting-passports/dashboard') {
      if (failDashboard) { res.statusCode = 503; res.end('{}'); return; }
      const daily = rows.map(row => ({ date: row.date.slice(0, 10), passports: 1, fabric_kg: row.meter_mode ? 0 : row.actual_kg, fabric_m: row.meter_mode ? row.actual_kg : 0, rolls: row.rolls_count, pieces: row.pieces * (row.tepa_pass ? 2 : 1) }));
      const totals = { passports: 0, fabric_kg: 0, fabric_m: 0, rolls: 0, pieces: 0 };
      for (const day of daily) for (const key in totals) totals[key] += day[key];
      data = { totals, daily };
    } else if (url.pathname === '/api/cutting-passports/export.xlsx') {
      if (failExport) { res.statusCode = 503; res.end('{}'); return; }
      res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
      res.end(fs.readFileSync(path.join(root, 'scripts/fixtures/cutting-passports.xlsx'))); return;
    } else if (url.pathname === '/api/settings') data = {};
    else if (url.pathname === '/api/tasks/count') data = { count: 0 };
    res.end(JSON.stringify(data)); return;
  }
  res.setHeader('Content-Type', 'text/html;charset=utf-8');
  res.end(`<html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><style>${css}</style></head><body><div id="root"></div><script>${built.outputFiles[0].text.replaceAll('</script>', '<\\/script>')}</script></body></html>`);
});
const serve = process.argv.includes('--serve');
await new Promise(resolve => server.listen(serve ? 4317 : 0, '127.0.0.1', resolve));
const url = `http://127.0.0.1:${server.address().port}/cutting-passports?cutting_department=CUT`;
console.log(url);
if (!serve) {
  const browser = await chromium.launch({ channel: process.platform === 'win32' ? 'chrome' : undefined, headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  try {
    await page.goto(url);
    await page.getByText('CP-0106', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'passports.png'), fullPage: true });
    await page.getByRole('tab', { name: 'Dashboard', exact: true }).click();
    await page.locator('[data-metric="pieces"]').getByText('2,100', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, 'dashboard.png'), fullPage: true });
    await page.getByLabel('From date', { exact: true }).fill('2026-10-17');
    await page.getByLabel('To date', { exact: true }).fill('2026-10-17');
    await page.locator('[data-metric="pieces"]').getByText('600', { exact: true }).waitFor();
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export to Excel', exact: true }).click();
    assert.equal((await download).suggestedFilename(), 'cutting-passports-2026-10-17-2026-10-17.xlsx');
    assert.ok(requests.some(r => r.path.endsWith('export.xlsx') && r.query.includes('date_from=2026-10-17') && r.query.includes('date_to=2026-10-17')));
    await page.getByLabel('From date', { exact: true }).fill('2026-10-18');
    assert.equal(await page.getByRole('button', { name: 'Export to Excel', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'All time', exact: true }).click();
    await page.getByLabel('From date', { exact: true }).fill('2027-01-01');
    await page.getByText(dictionaries.en['passportReport.empty'], { exact: true }).waitFor();
    await page.getByRole('button', { name: 'All time', exact: true }).click();
    await page.getByRole('button', { name: dictionaries.en['page.cuttingPassports.newPassport'], exact: true }).click();
    await page.getByRole('button', { name: dictionaries.en['page.cuttingPassports.exampleLoad'], exact: true }).click();
    await page.getByLabel('Tepa pass', { exact: true }).check();
    await page.locator('input[type="number"][placeholder="240"]').fill('300');
    await page.screenshot({ path: path.join(out, 'tepa-pass.png'), fullPage: true });
    await page.getByRole('button', { name: 'Create', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('input[type="number"][placeholder="240"]'));
    assert.equal(writes.length, 1); assert.equal(writes[0].pieces, 300); assert.equal(writes[0].tepa_pass, true);
    records = structuredClone(sample);
    for (const lang of ['ru', 'uz']) {
      await page.setViewportSize({ width: 390, height: 844 }); await page.goto(url + '&lang=' + lang);
      await page.getByRole('tab', { name: dictionaries[lang]['passportReport.dashboard'], exact: true }).click();
      await page.locator('[data-metric="pieces"]').waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
      await page.screenshot({ path: path.join(out, `dashboard-${lang}-mobile.png`), fullPage: true });
    }
    await page.goto(url + '&denied=1');
    assert.equal(await page.getByRole('tab', { name: 'Dashboard', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Export to Excel', exact: true }).count(), 0);
    failDashboard = true; await page.goto(url);
    await page.getByRole('tab', { name: 'Dashboard', exact: true }).click();
    await page.getByRole('alert').getByText(dictionaries.en['passportReport.loadError']).waitFor();
    failExport = true;
    await page.getByRole('button', { name: 'Export to Excel', exact: true }).click();
    await page.getByText(dictionaries.en['passportReport.exportError'], { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: actual ERP shell/page; dates, export, totals, Tepa pass payload, EN/RU/UZ, mobile overflow, permission visibility, empty/error states. Synthetic data only.');
  } finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
}
