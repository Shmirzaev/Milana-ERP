// Local-only regression: all business API traffic is mocked.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const playwright = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(path.join(process.env.PLAYWRIGHT_MODULE, "index.js")).href : "playwright");
const { chromium } = playwright.default || playwright;
const base = process.env.PRICING_QA_URL || "http://localhost:4318";
assert.ok(["localhost", "127.0.0.1"].includes(new URL(base).hostname));
const me = { id: 1, name: "Local QA", email: "qa@example.com", role: "Super Admin",
  permissions: ["*", "admin.super"], factory_code: "MIL", assigned_factory_code: "MIL",
  available_factories: ["MIL"], access_configured: true };
const rows = Array.from({ length: 61 }, (_, i) => ({
  id: 61 - i, model_id: 61 - i, model_no: `QA-PRICE-${String(61 - i).padStart(3, "0")}`,
  variant_no: "1", model_name: "QA garment", model_category: "T-shirt", model_sizes: ["S"],
  model_image_url: null, variant_image_url: null, kroy_no: null, cutting_passport_id: null,
  date: null, fabric_width_m: null, lay_length_m: null, size_count: null, gramage: null,
  binding_kg_per_piece: null, fabric_price: null, sewing_cost: null, packaging_cost: 0.1,
  accessories: [], cost_price_uzs: null, selling_price: null, profit_percentage: null,
  exchange_rate: null, fabric_consumption: null, consumption_cost: null, binding_price: null,
  cost_price: null, difference: null, cutting_status: "new", purchasing_status: "new",
  accessories_status: "new", overall_status: "new", created_at: "2026-10-05T00:00:00Z",
  updated_at: "2026-10-05T00:00:00Z",
}));
const paths = ["/sales/price-requests", "/cutting/price-calculation", "/purchasing/price-calculation",
  "/inventory/accessory-pricing", "/finance/price-calculation"];
const result = {};
const settle = () => new Promise((resolve) => setTimeout(resolve, 150));
const browser = await chromium.launch({ headless: true });
try {
  for (const routePath of paths) {
    console.log(`Checking ${routePath}`);
    const context = await browser.newContext();
    try {
      await context.addInitScript(() => {
        localStorage.setItem("erp_lang", "en");
        window.__qaHidden = false; window.__qaOffline = false;
        Object.defineProperty(document, "visibilityState", { configurable: true,
          get: () => window.__qaHidden ? "hidden" : "visible" });
        Object.defineProperty(navigator, "onLine", { configurable: true, get: () => !window.__qaOffline });
      });
      const reads = [], errors = [];
      let failedPage = false;
      await context.route("**/api/**", async (route) => {
        const url = new URL(route.request().url());
        let body = [];
        if (url.pathname === "/api/auth/me") body = me;
        else if (url.pathname === "/api/price-calculation/requests") {
          const limit = Number(url.searchParams.get("limit"));
          assert.equal(limit, 50);
          const cursor = Number(url.searchParams.get("before_id") || Infinity);
          reads.push({ limit, cursor: Number.isFinite(cursor) ? cursor : null });
          if (cursor === 12 && !failedPage) {
            failedPage = true;
            await route.fulfill({ status: 400, contentType: "application/json",
              body: JSON.stringify({ detail: "Local QA: retry this page" }) });
            return;
          }
          body = rows.filter((row) => row.id < cursor).slice(0, limit);
        } else if (url.pathname.includes("/settings")) body = { company_name: "Local QA" };
        else if (url.pathname.includes("/notifications")) body = { items: [], unread_count: 0 };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      });
      const page = await context.newPage();
      page.on("pageerror", (error) => errors.push(error.message));
      await page.clock.install();
      await page.goto(`${base}${routePath}`, { waitUntil: "domcontentloaded", timeout: 120000 });
      await page.locator('[title^="QA-PRICE-061"], input[value="QA-PRICE-061"]').first().waitFor({ timeout: 60000 });
      assert.equal(await page.locator('[title^="QA-PRICE-001"], input[value="QA-PRICE-001"]').count(), 0);
      await page.getByRole("button", { name: "Load more", exact: true }).click();
      await page.getByRole("button", { name: "Load more", exact: true }).waitFor();
      assert.equal(await page.getByRole("button", { name: "Load more", exact: true }).isEnabled(), true);
      assert.equal(await page.locator('[title^="QA-PRICE-061"], input[value="QA-PRICE-061"]').count(), 1);
      await page.getByRole("button", { name: "Load more", exact: true }).click();
      await page.locator('[title^="QA-PRICE-001"], input[value="QA-PRICE-001"]').first().waitFor();
      assert.equal(reads.filter((read) => read.cursor === 12).length, 2);
      assert.ok(reads.every((read) => read.cursor === null || read.cursor === 12));
      assert.ok(reads.some((read) => read.cursor === 12));
      assert.equal(await page.getByRole("button", { name: "Load more", exact: true }).count(), 0);

      const activeReads = reads.length;
      await page.clock.runFor(12000); await settle();
      assert.ok(reads.length > activeReads, `${routePath}: visible polling did not run`);
      await page.evaluate(() => { window.__qaHidden = true; document.dispatchEvent(new Event("visibilitychange")); });
      await settle(); const hiddenReads = reads.length;
      await page.clock.runFor(11000); await settle();
      assert.equal(reads.length, hiddenReads, `${routePath}: polling while hidden`);
      await page.evaluate(() => {
        window.__qaHidden = false; window.__qaOffline = true;
        document.dispatchEvent(new Event("visibilitychange")); window.dispatchEvent(new Event("offline"));
      });
      await settle(); const offlineReads = reads.length;
      await page.clock.runFor(11000); await settle();
      assert.equal(reads.length, offlineReads, `${routePath}: polling while offline`);
      await page.evaluate(() => { window.__qaOffline = false; window.dispatchEvent(new Event("online")); });
      await page.clock.runFor(12000); await settle();
      assert.ok(reads.length > offlineReads, `${routePath}: polling did not resume`);
      assert.deepEqual(errors, []);
      result[routePath] = { olderRowReachable: true, failedPageRetry: true, hiddenPollingStopped: true,
        offlinePollingStopped: true, pollingResumed: true, reads, errors };
    } finally { await context.close(); }
  }
  const output = fileURLToPath(new URL("../../outputs/ismail-completion/", import.meta.url));
  mkdirSync(output, { recursive: true });
  writeFileSync(path.join(output, "pricing-browser.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(Object.fromEntries(Object.entries(result).map(([key, value]) => [key, { ...value, reads: value.reads.length }]))));
} finally { await browser.close(); }
