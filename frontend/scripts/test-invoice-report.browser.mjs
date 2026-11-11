// Actual local Next/FastAPI app with invoice_report_browser.py disposable fixtures.
import assert from "node:assert/strict";
import fs from "node:fs";
import { chromium } from "playwright";

const base = "http://127.0.0.1:18823";
const output = "../outputs/invoice-browser";
fs.mkdirSync(output, { recursive: true });
const fixture = JSON.parse(fs.readFileSync("../outputs/invoice-fixture.json", "utf8"));
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined, headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await context.addInitScript(() => localStorage.setItem("erp_lang", "en"));
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
try {
  const login = await context.request.post(`${base}/api/auth/login-json`, {
    data: { email: "admin@example.com", password: "test-admin-password-123!", factory_code: "MIL" },
  });
  assert.equal(login.status(), 200);
  const endpoint = `${base}/api/shipments/${fixture.shipment_id}/invoice`;
  const before = await (await context.request.get(endpoint)).json();
  await page.goto(`${endpoint}/print?lang=en`);
  await page.locator(".items").waitFor();
  assert.match(await page.locator(".sizes").last().innerText(), /\(S, M, L, XL\) × 24/);
  assert.match(await page.locator(".sizes").first().innerText(), /48 × 30, 50 × 30/);
  const layout = await page.locator(".items tbody tr").first().evaluate(row => ({
    height: row.getBoundingClientRect().height,
    font: getComputedStyle(row.querySelector("td")).fontSize,
    clipped: Array.from(row.cells).filter(cell => cell.scrollWidth > cell.clientWidth + 2).length,
  }));
  assert.equal(layout.font, "10px");
  assert(layout.height >= 30 && layout.height <= 32);
  assert.equal(layout.clipped, 0);
  await page.screenshot({ path: `${output}/invoice-screen.png`, fullPage: true });
  await page.emulateMedia({ media: "print" });
  assert.equal(await page.locator(".controls").isVisible(), false);
  assert.equal(await page.locator(".signatures").evaluate(el => getComputedStyle(el).fontSize), "10px");
  await page.screenshot({ path: `${output}/invoice-print.png`, fullPage: true });
  await page.emulateMedia({ media: "screen" });
  for (const lang of ["en", "ru", "uz"]) {
    for (const showPrices of [true, false]) {
      const excel = await context.request.get(`${endpoint}.xlsx?lang=${lang}&show_prices=${showPrices}`);
      assert.equal(excel.status(), 200);
      fs.writeFileSync(`${output}/invoice-${lang}-${showPrices}.xlsx`, await excel.body());
    }
  }
  assert.deepEqual(await (await context.request.get(endpoint)).json(), before);
  await page.goto(`${base}/warehouse-stock/shipments`);
  await page.getByRole("button", { name: "Today", exact: true }).waitFor();
  const search = page.getByPlaceholder("Search model, order, customer…");
  await search.fill("BM8010");
  const todayResponse = page.waitForResponse(response => response.url().includes("/api/warehouse-reports/shipments?") && response.url().includes("date_from="));
  await page.getByRole("button", { name: "Today", exact: true }).click();
  const today = await (await todayResponse).json();
  assert.equal(today.quantity, 195);
  assert.equal(today.shipment_count, 1);
  assert.equal(await search.inputValue(), "BM8010");
  const dates = await page.locator('input[type="date"]').evaluateAll(inputs => inputs.map(input => input.value));
  assert.equal(dates[0], dates[1]);
  const monthResponse = page.waitForResponse(response => response.url().includes("/api/warehouse-reports/shipments?") && response.url().includes("date_from=") && !response.url().includes(`date_from=${dates[0]}`));
  await page.getByRole("button", { name: "This month", exact: true }).click();
  const month = await (await monthResponse).json();
  assert.equal(month.quantity, 195);
  const monthDates = await page.locator('input[type="date"]').evaluateAll(inputs => inputs.map(input => input.value));
  assert(monthDates[0].endsWith("-01"));
  await page.screenshot({ path: `${output}/report-desktop.png`, fullPage: true });
  const downloadResponse = page.waitForResponse(response => response.url().includes("/api/warehouse-reports/shipments.xlsx?"));
  await page.getByRole("button", { name: "Download Excel", exact: true }).click();
  const reportExport = await downloadResponse;
  const exportUrl = new URL(reportExport.url());
  assert.equal(reportExport.status(), 200);
  assert.equal(exportUrl.searchParams.get("q"), "BM8010");
  assert.equal(exportUrl.searchParams.get("date_from"), monthDates[0]);
  assert.equal(exportUrl.searchParams.get("date_to"), monthDates[1]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${output}/report-phone.png`, fullPage: true });
  assert(await page.getByRole("button", { name: "Today", exact: true }).isVisible());
  assert.deepEqual(errors, []);
  fs.writeFileSync(`${output}/result.json`, JSON.stringify({ pass: true, layout, todayQuantity: today.quantity, monthQuantity: month.quantity, dates: monthDates, pageErrors: errors }, null, 2));
  console.log("PASS: actual invoice print/Excel, source readback, report shortcuts, search, export filters and phone layout.");
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png`, fullPage: true });
  throw error;
} finally {
  await browser.close();
}
