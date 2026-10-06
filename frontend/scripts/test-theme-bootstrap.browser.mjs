// Run against a local Next dev/start server; no ERP login or data writes.
import assert from "node:assert/strict";
import { chromium } from "playwright";

const url = new URL(process.env.FRONTEND_TEST_URL || "http://127.0.0.1:4318/login");
assert.ok(["localhost", "127.0.0.1", "[::1]"].includes(url.hostname), "Use a loopback test server");
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const context = await browser.newContext();
  await context.addInitScript(() => localStorage.setItem("erp_theme", "night"));
  const page = await context.newPage();
  const hydrationErrors = [];
  page.on("console", message => {
    if (/hydration|hydrated|did not match|server rendered HTML/i.test(message.text())) hydrationErrors.push(message.text());
  });
  page.on("pageerror", error => hydrationErrors.push(error.message));
  let previousNonce;
  for (let request = 0; request < 2; request++) {
    const response = await page.goto(url.href, { waitUntil: "networkidle" });
    assert.equal(response.status(), 200);
    await page.locator("#login-email").fill("theme-test@example.invalid");
    const bootstrap = await page.evaluate(() => {
      const script = [...document.scripts].find(node => node.textContent.includes('localStorage.getItem("erp_theme")'));
      return { nonce: script?.nonce, attribute: script?.getAttribute("nonce"), theme: document.documentElement.dataset.theme, colorScheme: document.documentElement.style.colorScheme };
    });
    assert.ok(bootstrap.nonce, "Theme bootstrap needs a nonce");
    assert.ok(response.headers()["content-security-policy"].includes(`'nonce-${bootstrap.nonce}'`), "Bootstrap must match the response CSP");
    assert.notEqual(bootstrap.nonce, previousNonce, "Each document needs a fresh nonce");
    assert.equal(bootstrap.attribute, "", "Browsers hide the nonce content attribute");
    assert.equal(bootstrap.theme, "night");
    assert.equal(bootstrap.colorScheme, "dark");
    previousNonce = bootstrap.nonce;
  }
  assert.deepEqual(hydrationErrors, [], "Theme hydration must be quiet without removing CSP protection");
  console.log("Theme bootstrap: persisted theme, per-request CSP nonce and hydration passed.");
} finally {
  await browser.close();
}
