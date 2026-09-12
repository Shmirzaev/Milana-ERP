// Run against a LOCAL Next server. Every API request uses a fixture/snapshot;
// no requests or credentials are sent to production.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const out = path.resolve(__dirname, '../../outputs/dashboard-preview');
fs.mkdirSync(out, { recursive: true });
const supplied = process.env.DASHBOARD_SNAPSHOT;
const snapshot = supplied ? JSON.parse(fs.readFileSync(supplied, 'utf8')) : null;
const origin = process.env.DASHBOARD_PREVIEW_URL || 'http://127.0.0.1:3212';
assert(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));

function fixture(days) {
  const end = new Date();
  const start = new Date(end); start.setDate(start.getDate() - days + 1);
  const daily = Array.from({ length: days }, (_, i) => {
    const d = new Date(start); d.setDate(d.getDate() + i);
    return { date: d.toISOString().slice(0, 10), cutting: i * 100, printing: i * 10, sewing: i * 50, packaging: i * 20 };
  });
  return { start: daily[0].date, end: daily.at(-1).date, timezone: 'Asia/Tashkent', updated_at: end.toISOString(),
    active_orders: 2, late_orders: 0, planned_quantity: 1200, by_status: { planning: 1, sewing: 1 },
    totals: Object.fromEntries(['cutting', 'printing', 'sewing', 'packaging'].map(k => [k, daily.reduce((s, p) => s + p[k], 0)])), daily,
    orders: [{ id: 1, order_no: 'TEST-BRANDED-001', type: 'branded_stock', qty: 600, status: 'planning', deadline: null },
      { id: 2, order_no: 'TEST-CLIENT-002', type: 'client_order', qty: 600, status: 'sewing', deadline: null }], orders_limit: 100 };
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH });
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1720, height: 1120 }, timezoneId: 'Asia/Tashkent' });
  let mode = 'normal'; let permissions = ['*'];
  await context.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    assert.equal(url.origin, origin);
    const send = body => route.fulfill({ json: body });
    if (url.pathname === '/api/auth/me') return send({ id: 1, name: 'System Admin', role: 'Super Admin', department: 'Management / Admin', factory_code: 'MIL', assigned_factory_code: 'MIL', available_factories: ['MIL'], permissions });
    if (url.pathname === '/api/dashboard/overview') {
      if (mode === 'error') return route.fulfill({ status: 403, json: { detail: 'Fixture failure' } });
      const days = Math.round((new Date(url.searchParams.get('end')) - new Date(url.searchParams.get('start'))) / 86400000) + 1;
      const data = structuredClone(snapshot?.[String(days)] || fixture(days));
      if (mode === 'empty') { data.active_orders = 0; data.late_orders = 0; data.planned_quantity = 0; data.by_status = {}; data.orders = []; for (const k in data.totals) data.totals[k] = 0; data.daily.forEach(p => { for (const k in data.totals) p[k] = 0; }); }
      return send(data);
    }
    if (url.pathname === '/api/dashboard/finance') return send(snapshot?.finance || { revenue_total: 0, payments_received: 0 });
    if (url.pathname.includes('/notifications/summary')) return send({ count: 0, rows: [] });
    if (url.pathname.includes('/tasks/count')) return send({ count: 0 });
    return send([]);
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('console', message => { if (message.type() === 'error' && mode === 'normal') errors.push(message.text()); });
  await page.goto(origin);
  await page.getByRole('heading', { name: 'Daily production output' }).waitFor();
  if (snapshot) assert((await page.locator('main a[href^="/usluga/orders/"]').count()) > 0);
  await page.screenshot({ path: path.join(out, 'dashboard-desktop.png'), fullPage: true });
  await page.getByLabel('Selected period', { exact: true }).selectOption('7');
  await page.waitForResponse(r => r.url().includes('/api/dashboard/overview') && r.ok());
  await page.getByRole('heading', { name: 'Daily production output' }).waitFor();
  await page.getByRole('button', { name: 'Cutting', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Cutting', exact: true }).getAttribute('aria-pressed'), 'false');
  await page.getByRole('button', { name: 'Cutting', exact: true }).click();
  await page.getByLabel('Find an order').fill('NO-SUCH-ORDER');
  await page.getByText('No active orders match this filter.').waitFor();
  await page.getByLabel('Find an order').fill('');
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export daily output' }).click();
  const file = await download;
  await file.saveAs(path.join(out, 'output.csv'));
  assert.equal(fs.readFileSync(path.join(out, 'output.csv'), 'utf8').split('\r\n').length, 8);
  for (const lang of ['ru', 'uz', 'en']) {
    await page.evaluate(lang => localStorage.setItem('erp_lang', lang), lang);
    await page.reload();
    await page.getByRole('heading', { name: lang === 'ru' ? 'Ежедневный выпуск' : lang === 'uz' ? 'Kunlik ishlab chiqarish' : 'Daily production output' }).waitFor();
    await page.screenshot({ path: path.join(out, `dashboard-${lang}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(200);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: path.join(out, 'dashboard-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1720, height: 1120 });
  await page.evaluate(() => localStorage.setItem('erp_theme', 'night'));
  await page.reload();
  await page.getByRole('heading', { name: 'Daily production output' }).waitFor();
  await page.screenshot({ path: path.join(out, 'dashboard-night.png'), fullPage: true });
  await page.evaluate(() => localStorage.setItem('erp_theme', 'day'));
  mode = 'empty'; await page.reload();
  await page.getByText('No output recorded in this period.').waitFor();
  await page.getByText('No active production orders', { exact: true }).waitFor();
  mode = 'error'; await page.reload();
  await page.getByText('Dashboard data could not be loaded. Please retry.', { exact: false }).waitFor();
  assert.equal(await page.getByRole('heading', { name: 'Daily production output' }).count(), 0);
  mode = 'normal'; permissions = ['management.view']; await page.reload();
  await page.getByRole('heading', { name: 'Daily production output' }).waitFor();
  assert.equal(await page.getByRole('link', { name: 'New order', exact: true }).count(), 0);
  assert.equal(await page.getByRole('heading', { name: 'Finance · all time' }).count(), 0);
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('PASS: desktop/mobile, EN/RU/UZ, period, series toggles, search, CSV, empty/error and restricted permissions; zero page exceptions.');
})().catch(error => { console.error(error); process.exit(1); });
