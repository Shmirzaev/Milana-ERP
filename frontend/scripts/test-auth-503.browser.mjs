import assert from "node:assert/strict";
import { chromium } from "playwright";

const origin = new URL(process.env.AUTH503_BROWSER_URL || "http://localhost:3000");
assert.ok(["localhost", "127.0.0.1"].includes(origin.hostname), "Use an isolated local frontend");
const detail = "Authentication is temporarily unavailable. Try again later.";
const browser = await chromium.launch();
try {
  const page = await browser.newPage();
  await page.route("**/api/auth/login-panel**", route => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ active_orders: 0, todays_receipts: 0, late_orders: 0, production_14d: [], open_tasks: [] }),
  }));
  const counts = { login: 0, forgot: 0, reset: 0 };
  for (const [kind, pathname] of [
    ["login", "/api/auth/login-json"],
    ["forgot", "/api/auth/forgot-password"],
    ["reset", "/api/auth/reset-password"],
  ]) {
    await page.route(`**${pathname}`, route => {
      counts[kind]++;
      return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail }) });
    });
  }

  await page.goto(new URL("/login", origin).href);
  await page.locator("#login-email").fill("test@example.invalid");
  await page.locator("#login-password").fill("test-password");
  await page.locator("form").first().locator('button[type="submit"]').click();
  await page.getByText(`503: ${detail}`, { exact: true }).waitFor({ timeout: 1500 });
  assert.equal(counts.login, 1, "login 503 must render without backoff or replay");

  await page.getByTestId("forgot-password-open").click();
  await page.getByTestId("forgot-password-email").fill("test@example.invalid");
  await page.getByTestId("forgot-password-submit").click();
  await page.getByText(`503: ${detail}`, { exact: true }).last().waitFor({ timeout: 1500 });
  assert.equal(counts.forgot, 1, "password-reset request 503 must not replay");

  await page.goto(new URL("/reset-password?token=test-token", origin).href);
  await page.locator('input[type="password"]').first().fill("test-password");
  await page.locator('input[type="password"]').last().fill("test-password");
  await page.locator('form button[type="submit"]').click();
  await page.getByText(detail, { exact: true }).waitFor({ timeout: 1500 });
  assert.equal(counts.reset, 1, "password-reset completion 503 must not replay");
  console.log("Browser: login, reset request and reset completion show one 503 without retries.");
} finally {
  await browser.close();
}
