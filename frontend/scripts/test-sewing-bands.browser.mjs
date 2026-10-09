import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'esbuild';
import { chromium } from 'playwright';

const root = process.cwd();
const stubs = {
  '@/lib/auth': `export const logout=()=>{};`,
  'next/navigation': `export const usePathname=()=>window.testPath;`,
  'next/link': `export default function Link({children,...props}) {return <a {...props}>{children}</a>}`,
  '@/lib/i18n': `import {useState} from 'react'; export const useT=()=>{const [lang,setLang]=useState(window.testLang||'en');return {lang,setLang,t:k=>k};};`,
  '@/lib/api': `
    export const fetcher=async url=> url.startsWith('/api/sewing-daily')?{rows:[]}:window.bands;
    async function post(path,body,headers){window.calls.push({path,body,headers});if(window.failOnce){window.failOnce=false;throw Error('Network interrupted');}return {received_count:1};}
    export const api={post,postWithHeaders:post,patch:post,get:async()=>[]};`,
};
const entry = `import React from 'react';import {createRoot} from 'react-dom/client';import Workspace from './src/components/sewing/BandWorkspace';import Progress from './src/components/sewing/BandProgress';
createRoot(document.getElementById('root')).render(window.manager?<Progress manager jobs={window.bands[0].jobs}/>:<Workspace me={{id:9,name:'Band 1',sewing_band_id:64}}/>);`;
const built = await build({ stdin: { contents: entry, resolveDir: root, loader: 'tsx' }, bundle: true, write: false, format: 'iife', jsx: 'automatic', plugins: [{ name: 'fixtures', setup(b) {
  b.onResolve({ filter: /^(?:@\/|next\/)/ }, args => args.path in stubs ? { path: args.path, namespace: 'fixtures' } : undefined);
  b.onLoad({ filter: /.*/, namespace: 'fixtures' }, args => ({ contents: stubs[args.path], loader: 'tsx', resolveDir: root }));
} }] });
const job = { id: 41, work_order_id: 81, production_order_id: 71, production_batch_id: 91, order_no: 'PO-100', model: '1001-1', batch: 'Kroy 1', quantity: 100, reported_qty: 40, actual_qty: 0, top_qty: 40, bottom_qty: 40, line_finished: false, awaiting_final: false, finish_reason: null, status: 'planned' };
const browser = await chromium.launch({ channel: process.platform === 'win32' ? 'chrome' : undefined });
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
  await page.route('http://localhost:3199/**', route => route.fulfill({ contentType: 'text/html', body: '<div id="root"></div>' }));
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  async function load(options = {}) {
    await page.goto('http://localhost:3199/band-test');
    await page.evaluate(opts => Object.assign(window, opts), { calls: [], testPath: '/sewing/flows', bands: [{ id: 64, name: '1-Band', jobs: [job] }], ...options });
    await page.addScriptTag({ content: built.outputFiles[0].text });
  }
  await load(); await page.getByText('Reported progress: 40 / 100', { exact: false }).waitFor();
  assert.equal(await page.getByRole('progressbar').getAttribute('value'), '40');
  await page.getByRole('button', { name: 'Enter final output', exact: true }).click();
  await page.getByLabel('Accepted pieces', { exact: true }).fill('40');
  await page.getByRole('button', { name: 'Save actual order output', exact: true }).click();
  await page.waitForFunction(() => window.calls.length === 1);
  assert.equal((await page.evaluate(() => window.calls[0])).body.sewing_assignment_id, 41);
  assert.equal((await page.evaluate(() => window.calls[0])).body.input_qty, 0);
  await load({ testPath: '/sewing/daily-report', failOnce: true });
  await page.getByLabel('Select assigned work', { exact: true }).selectOption('41');
  assert.equal(await page.locator('select option').filter({ hasText: 'Band 2' }).count(), 0);
  await page.getByLabel('Sewn today', { exact: true }).fill('25');
  await page.getByRole('button', { name: 'Save report', exact: true }).click();
  await page.getByRole('alert').waitFor();
  await page.getByRole('button', { name: 'Save report', exact: true }).click();
  await page.waitForFunction(() => window.calls.length === 2);
  const writes = await page.evaluate(() => window.calls);
  assert.equal(writes[0].body.sewing_flow_id, 64);
  assert.equal(writes[0].body.sewing_assignment_id, 41);
  assert.equal(writes[0].headers['Idempotency-Key'], writes[1].headers['Idempotency-Key']);
  await load({ bands: [{ id: 64, name: '1-Band', jobs: [{ ...job, reported_qty: 100, line_finished: true, awaiting_final: true }] }] });
  await page.getByText('Available — needs work', { exact: true }).waitFor();
  await page.locator('summary').click(); await page.getByText('Awaiting final order output', { exact: true }).waitFor();
  await load({ testPath: '/bundles/scan/sewing' });
  await page.getByLabel('Scan bundle QR / barcode', { exact: true }).fill('BUNDLE-123');
  await page.getByRole('button', { name: 'Receive and assign to my band', exact: true }).click();
  await page.waitForFunction(() => window.calls.length === 1);
  assert.deepEqual((await page.evaluate(() => window.calls[0])).body, { code: 'BUNDLE-123' });
  for (const [testLang, heading] of [['ru', 'Ежедневный швейный отчёт'], ['uz', 'Kunlik tikuv hisoboti']]) {
    await load({ testPath: '/sewing/daily-report', testLang });
    await page.getByRole('heading', { name: `${heading} · 1-Band`, exact: true }).waitFor();
  }
  await load({ manager: true });
  await page.getByRole('button', { name: 'Finish line work', exact: true }).click();
  await page.getByLabel('Reason for finishing or reopening this line assignment', { exact: true }).fill('Shortfall');
  await page.getByRole('button', { name: 'Finish line work', exact: true }).last().click();
  await page.waitForFunction(() => window.calls.length === 1);
  assert.deepEqual((await page.evaluate(() => window.calls[0])).body, { reason: 'Shortfall', finished: true });
  await load();
  const output = path.resolve(root, '../outputs/band-preview'); fs.mkdirSync(output, { recursive: true });
  await page.getByRole('progressbar').waitFor();
  await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'phone.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  console.log('Band workspace: scoped work, reports, retry keys, progress, availability, separate output, receipt, manager finish, EN/RU/UZ and phone layout passed.');
} finally { await browser.close(); }
