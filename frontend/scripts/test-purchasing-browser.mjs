// Run a local frontend with: bun run dev --port 4317.
// Run this script with Node/Bun and Playwright installed, or set
// PLAYWRIGHT_MODULE to an external Playwright package directory.
// All API requests are mocked. No production connection or business writes.
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const specifier = process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(path.join(process.env.PLAYWRIGHT_MODULE, "index.js")).href
  : "playwright";
const playwright = await import(specifier);
const { chromium } = playwright.default || playwright;
const base = process.env.PURCHASING_QA_URL || "http://localhost:4317";
assert.ok(["localhost", "127.0.0.1"].includes(new URL(base).hostname));
const output = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../outputs/ismail-review-qa");
mkdirSync(output, { recursive: true });
const me = {
  id: 1, name: "Local Review", email: "review@example.com", role: "Super Admin",
  permissions: ["*", "admin.super"], factory_code: "MIL", assigned_factory_code: "MIL",
  available_factories: ["MIL"], access_configured: true,
};
const orders = Array.from({ length: 52 }, (_, i) => ({
  id: i + 1, po_no: `QA-ORDER-${String(i + 1).padStart(3, "0")}`,
  supplier_id: 1, supplier_name: "QA Supplier", status: "sent", expected_date: "2026-10-04",
  lines: [{
    id: i + 1, item_id: 1, item_sku: "QA", item_name: "QA Material", material_name: "QA Material",
    ordered_quantity: 5, received_quantity: 0, remaining_quantity: 5, unit: "kg", unit_cost: 2,
    warehouse_id: 1, warehouse_name: "QA Warehouse", supplier_id: 1, supplier_name: "QA Supplier",
  }],
}));
const browser = await chromium.launch({ headless: true });
const result = {};
try {
  for (const pending of [false, true]) {
    const context = await browser.newContext();
    try {
      await context.addInitScript(({ pending }) => {
        localStorage.setItem("erp_lang", "en");
        if (pending) {
          sessionStorage.setItem("purchase-receipt:1:52:52", JSON.stringify({
            key: "rcpt-review-stable", orderId: 52, lineId: 52, label: "QA-ORDER-052",
            body: {
              supplier_id: 1, close_order: false,
              lines: [{ purchase_order_line_id: 52, received_quantity: 5, roll_weights_kg: [5],
                warehouse_id: 1, batch_no: "QA-RETRY", piece_count: 1, cost_per_unit: 2 }],
            },
          }));
        }
      }, { pending });
      const offsets = [], errors = [], receiptKeys = [];
      await context.route("**/api/**", async (route) => {
        const url = new URL(route.request().url());
        let body = [];
        if (url.pathname === "/api/auth/me") body = me;
        else if (url.pathname.endsWith("/52/receive")) {
          receiptKeys.push(route.request().headers()["idempotency-key"]);
          if (receiptKeys.length === 1) {
            await route.fulfill({ status: 500, contentType: "application/json",
              body: JSON.stringify({ detail: "Temporary QA failure" }) });
            return;
          }
          body = orders[51];
        } else if (url.pathname === "/api/purchasing/orders") {
          const offset = Number(url.searchParams.get("offset") || 0);
          const limit = Number(url.searchParams.get("limit") || 50);
          if (url.searchParams.get("receivable_only") === "true") {
            body = { items: orders.slice(0, 1), total: 61, limit: 1, offset: 0 };
          } else {
            offsets.push(offset);
            // Slow page two exposes uncontrolled useEffect page growth.
            if (offset > 0) await new Promise((resolve) => setTimeout(resolve, 1000));
            body = { items: orders.slice(offset, offset + limit), total: 52, limit, offset };
          }
        } else if (url.pathname === "/api/inventory/warehouses") {
          body = [{ id: 1, name: "QA Warehouse", type: "fabric_storage" }];
        } else if (url.pathname.includes("/settings")) body = { company_name: "Local QA" };
        else if (url.pathname.includes("/notifications")) body = { items: [], unread_count: 0 };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
      });
      const page = await context.newPage();
      page.on("pageerror", (error) => errors.push(error.message));
      if (!pending) {
        await page.goto(`${base}/purchasing`, { waitUntil: "domcontentloaded", timeout: 120000 });
        await page.getByRole("link", { name: /\(61\)/ }).waitFor({ timeout: 60000 });
        result.counter = "61 displayed from filtered server total";
      }
      await page.goto(`${base}/purchasing/receiving`, { waitUntil: "domcontentloaded", timeout: 120000 });
      if (!pending) {
        await page.getByRole("button", { name: "Load more", exact: true }).click({ timeout: 60000 });
      }
      // Scope to the table: the recovery banner already contains this label.
      await page.locator("table").getByText("QA-ORDER-052", { exact: true }).waitFor({ timeout: 60000 });
      if (pending) {
        const retry = page.getByRole("button", { name: "Retry the saved receipt", exact: true });
        await retry.click();
        await page.getByText("This receipt was not confirmed. Sending it again reuses the same receipt key, so the goods are received only once.", { exact: true }).waitFor();
        await page.locator("form").getByRole("button", { name: "Receive", exact: true }).click();
        await page.locator("form").getByText("Temporary QA failure", { exact: false }).waitFor();
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.locator("table").getByText("QA-ORDER-052", { exact: true }).waitFor();
        await retry.click();
        await page.locator("form").getByRole("button", { name: "Receive", exact: true }).click();
        await retry.waitFor({ state: "detached" });
        assert.deepEqual(receiptKeys, ["rcpt-review-stable", "rcpt-review-stable"]);
        result.receiptKeys = receiptKeys;
      }
      assert.deepEqual(errors, []);
      assert.deepEqual([...new Set(offsets)], [0, 50]);
      // Includes SWR revalidation after failure, reload and successful receipt.
      assert.ok(offsets.length <= 12, "paging must not loop");
      result[pending ? "pending" : "manual"] = { offsets, errors };
    } finally {
      await context.close();
    }
  }
  writeFileSync(path.join(output, "browser-result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}