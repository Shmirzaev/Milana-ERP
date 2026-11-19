// Actual Next/FastAPI app on disposable loopback fixtures; never use production.
// Start backend/app/tests/sewing_receive_pagination_browser.py and Next on 18823
// with API_URL=http://127.0.0.1:18822. Restart fixtures before repeating this test.
import assert from "node:assert/strict";
import fs from "node:fs";
import { chromium } from "playwright";

const base = "http://127.0.0.1:18823";
const fixture = JSON.parse(fs.readFileSync("../outputs/load-more/fixture.json", "utf8"));
const output = "../outputs/load-more";
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined, headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await context.addInitScript(() => localStorage.setItem("erp_lang", "en"));
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const calls = [];
let failOffset = null;
await page.route("**/api/bundles/sewing-receive-options?*", async route => {
  const url = new URL(route.request().url());
  calls.push(Object.fromEntries(url.searchParams));
  if (url.searchParams.get("offset") === failOffset) {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Pagination QA temporary failure" }) });
  } else await route.continue();
});
const rows = () => page.locator("table tbody tr").filter({ has: page.getByRole("button", { name: "Receive batch", exact: true }) });
const loadMore = () => page.getByRole("button", { name: "Load more", exact: true });
async function count(expected) {
  await page.waitForFunction(n => document.querySelectorAll("table tbody tr select").length === n, expected);
  assert.equal(await rows().count(), expected);
}
async function login(factory) {
  const response = await context.request.post(`${base}/api/auth/login-json`, {
    data: { email: "admin@example.com", password: "test-admin-password-123!", factory_code: factory },
  });
  assert.equal(response.status(), 200);
  await page.goto(`${base}/bundles/scan/sewing?factory=${factory}`);
  await count(Math.min(20, fixture[factory].ids.length));
}
async function search(value) {
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Search", exact: true }) });
  await form.locator("input").fill(value);
  await form.getByRole("button", { name: "Search", exact: true }).click();
}

try {
  await login("MIL");
  await search(fixture.MIL.order);
  await count(20);
  const select = rows().first().locator("select");
  const choice = await select.locator("option").nth(1).getAttribute("value");
  await select.selectOption(choice);
  await loadMore().click();
  await count(40);
  assert.equal(await rows().first().locator("select").inputValue(), choice);
  await loadMore().click();
  await count(49);
  assert.equal(await loadMore().count(), 0);
  assert.equal(new Set(await rows().locator("td:nth-child(2)").allTextContents()).size, 49);
  await page.screenshot({ path: `${output}/49-nastils-desktop.png`, fullPage: true });
  // Returning to a cached query must reset to the first 20, too.
  await search("no-such-order");
  await count(0);
  await search(fixture.MIL.order);
  await count(20);
  // Exercise a page that is not already present in SWR's per-page cache.
  await search(fixture.MIL.order.toUpperCase());
  await count(20);
  failOffset = "20";
  await loadMore().click();
  await page.getByRole("alert").filter({ hasText: "Pagination QA" }).waitFor();
  await count(20);
  failOffset = null;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await count(40);
  await loadMore().click();
  await count(49);
  // Real receipt POST and DB-backed GET refresh all accumulated pages.
  const acceptedBatch = (await rows().first().locator("td").nth(1).textContent()).trim();
  await rows().first().locator("select").selectOption("");
  const receiptResponse = page.waitForResponse(r => r.url().endsWith("/api/bundles/manual-receive-sewing") && r.request().method() === "POST");
  await rows().first().getByRole("button", { name: "Receive batch", exact: true }).click();
  assert.equal((await receiptResponse).status(), 200);
  await count(48);
  assert(!(await rows().locator("td:nth-child(2)").allTextContents()).map(s => s.trim()).includes(acceptedBatch));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await count(48);
  // Over 100 eligible groups must remain reachable with fixed-size requests.
  await login("BST");
  await search(fixture.BST.order);
  await count(20);
  for (const total of [40, 60, 80, 100, 120, 123]) {
    await loadMore().click();
    await count(total);
  }
  assert.equal(new Set(await rows().locator("td:nth-child(2)").allTextContents()).size, 123);
  assert.equal(await loadMore().count(), 0);
  await login("ECO");
  await count(3);
  assert.equal(await loadMore().count(), 0);
  await login("MIL");
  await count(20);
  await page.setViewportSize({ width: 390, height: 844 });
  await loadMore().scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${output}/load-more-phone.png` });
  assert(await loadMore().isVisible());
  await page.setViewportSize({ width: 1440, height: 1000 });
  await loadMore().scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${output}/load-more-desktop.png` });
  assert(calls.every(call => call.limit === "20"));
  assert(calls.some(call => call.offset === "120"));
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${output}/browser-result.json`, JSON.stringify({ pass: true, calls: calls.length, maxOffset: 120, pageErrors: errors, checks: ["49 rows", "123 rows", "unique batches", "selected line preserved", "cached search reset", "error retry", "persisted receipt refresh", "factory reset", "phone layout"] }, null, 2));
  console.log("PASS: actual Next/FastAPI receiving app: pagination, cached search, scope, retry, receipt refresh and phone layout.");
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  fs.writeFileSync(`${output}/failure.json`, JSON.stringify({ error: String(error), calls, text: await page.locator("body").innerText() }, null, 2));
  throw error;
} finally {
  await browser.close();
}
