// SEC04 gate 3: real ERP login, model image, and revoked-session refusals.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "playwright";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const stack = path.resolve(root, "scripts/sec04_local_stack.py");
const output = path.resolve(root, "outputs/sec04-verification/browser");
const base = "http://127.0.0.1:3000";
const file = "/storage/model-files/sec04-verification.png";
const thumb = "/storage/model-files/thumb/sec04-verification.png?size=160";
mkdirSync(output, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
const network = [];
const pageErrors = [];
const cachedRequests = [];
const cdp = await context.newCDPSession(page);
await cdp.send("Network.enable");
cdp.on("Network.requestServedFromCache", ({ requestId }) => cachedRequests.push(requestId));
page.on("response", (response) => {
  if (response.url().includes("/storage/model-files/")) {
    network.push({ path: new URL(response.url()).pathname, status: response.status() });
  }
});
page.on("pageerror", (error) => pageErrors.push(error.message));

try {
  await page.goto(`${base}/login`);
  await page.locator("#login-factory").selectOption("MIL");
  await page.locator("#login-email").fill("sec04-viewer@example.com");
  await page.locator("#login-password").fill(process.env.SEC04_VIEWER_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
  const session = (await context.cookies()).find((cookie) => cookie.name === "erp_access_token");
  assert.ok(session, "real browser login must set an auth cookie");

  await page.goto(`${base}/models`);
  await page.getByText("SEC04 Verification Model").first().waitFor();
  const image = page.getByAltText("SEC04 Verification Model").first();
  await image.scrollIntoViewIfNeeded();
  await page.waitForFunction((selector) => {
    const element = document.querySelector(selector);
    return element instanceof HTMLImageElement && element.complete && element.naturalWidth > 0;
  }, 'img[alt="SEC04 Verification Model"]');
  await page.screenshot({ path: path.join(output, "01-model-list.png"), fullPage: true });

  for (const [route, name] of [[file, "02-file.png"], [thumb, "03-thumbnail.png"]]) {
    const response = await page.goto(base + route);
    assert.equal(response.status(), 200);
    await page.screenshot({ path: path.join(output, name) });
  }

  execFileSync("python3", [stack, "revoke"], { stdio: "pipe" });
  assert.equal((await context.cookies()).find((cookie) => cookie.name === "erp_access_token")?.value,
               session.value, "revocation must test the retained session");
  const revokedResponses = [];
  for (const [route, name] of [[file, "04-revoked-file.png"], [thumb, "05-revoked-thumbnail.png"]]) {
    const response = await page.goto(base + route);
    await page.screenshot({ path: path.join(output, name) });
    revokedResponses.push({ path: route, status: response.status(),
      cacheControl: response.headers()["cache-control"], body: (await page.locator("body").innerText()).slice(0, 200) });
  }

  const readback = JSON.parse(execFileSync("python3", [stack, "readback"], { encoding: "utf8" }));
  assert.equal(readback.is_active, false);
  assert.equal(readback.image_records, 1);
  assert.equal(readback.file_exists, true);
  assert.ok(network.some((response) => response.path === file && response.status === 200));
  assert.ok(network.some((response) => response.path.includes("/thumb/") && response.status === 200));
  assert.deepEqual(pageErrors, []);
  writeFileSync(path.join(output, "results.json"), JSON.stringify({ network, revokedResponses,
    cachedRequestCount: cachedRequests.length, readback, pageErrors }, null, 2));
  assert.deepEqual(revokedResponses.map(({ status }) => status), [401, 401]);
  assert.ok(revokedResponses.every(({ body }) => /Inactive or unknown user/.test(body)));
  assert.ok(network.some((response) => response.path === file && response.status === 401));
  assert.ok(network.some((response) => response.path.includes("/thumb/") && response.status === 401));
  console.log(`PASS: real login, visible model image, file/thumbnail 200 then 401; evidence ${output}`);
} finally {
  await browser.close();
}
