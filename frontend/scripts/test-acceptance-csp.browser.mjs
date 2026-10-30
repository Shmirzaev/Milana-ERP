// OPS09: run against an isolated production Next + Nginx TLS + fixture backend.
// Fixture setup uses fixtures/acceptance_csp_backend.py; never point at production.
import assert from "node:assert/strict";
import fs from "node:fs";
import https from "node:https";
import path from "node:path";
import { isIP } from "node:net";
import test from "node:test";
import { build } from "esbuild";
import { chromium } from "playwright";

const origin = new URL(process.env.ACCEPTANCE_CSP_URL || "https://127.0.0.1:18443");
assert.equal(origin.protocol, "https:", "The closing test requires real TLS");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname), "Isolated loopback target only");
assert.ok(process.env.ACCEPTANCE_CSP_MANIFEST, "Provide the disposable fixture manifest");
const manifest = JSON.parse(fs.readFileSync(process.env.ACCEPTANCE_CSP_MANIFEST, "utf8"));
assert.equal(manifest.database, "fresh temporary SQLite");
for (const key of ["bundle", "packages"]) assert.match(manifest[key], /^\/api\//);
const output = path.resolve(process.env.ACCEPTANCE_CSP_OUTPUT || ".codex-work/ops09-browser");
fs.mkdirSync(output, { recursive: true });

const getResponse = (pathname, headers) => new Promise((resolve, reject) => {
  https.get(new URL(pathname, origin), { rejectUnauthorized: false, headers: Array.isArray(headers) ? ["Host", origin.host, ...headers] : headers, signal: AbortSignal.timeout(10_000) }, response => {
    let body = "";
    response.setEncoding("utf8");
    response.on("data", chunk => { body += chunk; });
    response.on("end", () => resolve({ status: response.statusCode, headers: response.headers, body }));
  }).on("error", reject);
});
const nonceFrom = policy => policy?.match(/'nonce-([^']+)'/)?.[1];
await test("SEC09-PROXY: intended TLS edge preserves scheme and client through Next and HAProxy", async () => {
  const observations = [];
  try {
    for (const fields of [
      ["X-Forwarded-Proto", "http", "X-Forwarded-For", "203.0.113.66"],
      ["X-Forwarded-Proto", "https", "X-Forwarded-Proto", "http",
        "X-Forwarded-For", "203.0.113.66", "X-Forwarded-For", "198.51.100.10"],
    ]) {
      const response = await getResponse("/health", fields);
      const observed = Object.fromEntries(["edge-client", "peer", "client", "rate-client", "scheme"]
        .map(key => [key, response.headers[`x-acceptance-${key}`]]));
      observations.push(observed);
      assert.equal(response.status, 200);
      assert.ok(isIP(observed["edge-client"]), "Nginx must independently record its actual socket peer");
      assert.equal(observed.peer, "127.0.0.1", "Uvicorn must retain its actual HAProxy socket peer");
      assert.equal(observed.scheme, "https", "TLS edge must replace forged/duplicate forwarded schemes");
      assert.equal(observed.client, observed["edge-client"], "Effective client must equal the real edge peer, not attacker XFF");
      assert.equal(observed["rate-client"], observed.client);
      assert.ok(!["203.0.113.66", "198.51.100.10"].includes(observed.client));
    }
  } finally {
    fs.writeFileSync(path.join(output, "tls-edge-results.json"), JSON.stringify({ observations }, null, 2));
  }
});

await test("OPS09-WEB: production browser enforces CSP and preserves hydration, HTTPS cookies and label print", async () => {
const documents = await Promise.all([
  getResponse("/login"), getResponse("/login", { "x-nonce": "attacker-nonce", "Content-Security-Policy": "script-src 'unsafe-inline'" }),
]);
const nonces = documents.map(document => {
  assert.equal(document.status, 200);
  assert.match(document.headers["strict-transport-security"] || "", /max-age=31536000/);
  const nonce = nonceFrom(document.headers["content-security-policy"]);
  assert.ok(nonce && nonce !== "attacker-nonce", "Server must replace a forged caller nonce");
  const executableScripts = [...document.body.matchAll(/<script\b([^>]*)>[\s\S]*?<\/script>/gi)]
    .map(match => match[1]).filter(attributes => {
      const type = attributes.match(/\btype=["']([^"']*)["']/i)?.[1].toLowerCase();
      return !type || ["module", "text/javascript", "application/javascript", "text/ecmascript", "application/ecmascript"].includes(type);
    });
  assert.ok(executableScripts.length > 0);
  assert.ok(executableScripts.every(attributes => attributes.match(/\bnonce=["']([^"']+)["']/i)?.[1] === nonce),
    "Every executable script, including any missing a nonce, must match response nonce");
  return nonce;
});
assert.notEqual(nonces[0], nonces[1], "Fresh nonce for every actual HTTP response");

const apiBundle = await build({
  entryPoints: [path.resolve(import.meta.dirname, "../src/lib/api.ts")],
  bundle: true, write: false, format: "iife", globalName: "acceptanceApi", platform: "browser",
});
const browser = await chromium.launch();
const result = { checks: ["fresh response nonces, forged nonce replacement and every executable script nonce"], violations: [], printed: [], screenshots: [], pageErrors: [] };
try {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  await context.addInitScript(() => {
    localStorage.setItem("erp_theme", "night");
    window.__acceptancePrintCalls = 0;
    window.print = () => { window.__acceptancePrintCalls++; };
    window.__acceptanceViolations = [];
    window.addEventListener("securitypolicyviolation", event => window.__acceptanceViolations.push({
      directive: event.effectiveDirective, blocked: event.blockedURI,
    }));
  });
  const page = await context.newPage();
  const errors = result.pageErrors;
  page.on("pageerror", error => errors.push(error.message));
  const response = await page.goto(new URL("/login", origin).href, { waitUntil: "networkidle" });
  assert.equal(response.status(), 200);
  const nonce = nonceFrom(response.headers()["content-security-policy"]);
  assert.ok(nonce);
  assert.equal(await page.locator("html").getAttribute("data-theme"), "night", "Approved theme bootstrap must execute");
  await page.locator("#login-email").fill(manifest.login_email);
  await page.getByTestId("forgot-password-open").click();
  await page.locator("#forgot-password-email").waitFor({ state: "visible" });
  result.checks.push("production hydration and nonce-approved theme bootstrap");

  await page.evaluate(({ nonce, bundle }) => {
    const blocked = document.createElement("script");
    blocked.textContent = "window.__acceptanceUnapprovedExecuted = true";
    document.head.append(blocked);
    const approved = document.createElement("script");
    approved.nonce = nonce;
    approved.textContent = `${bundle}\nwindow.__acceptanceApprovedExecuted = true;`;
    document.head.append(approved);
  }, { nonce, bundle: apiBundle.outputFiles[0].text });
  await page.waitForFunction(() => window.__acceptanceViolations.length > 0);
  assert.equal(await page.evaluate(() => window.__acceptanceUnapprovedExecuted), undefined, "Unnonced script must never execute");
  assert.equal(await page.evaluate(() => window.__acceptanceApprovedExecuted), true, "Matching-nonce positive control must execute");
  result.violations.push(...await page.evaluate(() => window.__acceptanceViolations));
  assert.ok(result.violations.some(v => v.directive === "script-src-elem" && v.blocked === "inline"));
  result.checks.push("browser enforced CSP: unnonced rejected, approved nonce executed");

  const login = await context.request.post(new URL("/api/auth/login-json", origin).href, {
    data: { email: manifest.login_email, password: process.env.ACCEPTANCE_CSP_LOGIN_PASSWORD || "test-admin-password-123!", factory_code: "MIL" },
  });
  assert.equal(login.status(), 200, "Isolated actual backend login must succeed");
  const cookieFlags = (login.headers()["set-cookie"] || "").split(";").slice(1).join(";");
  assert.match(cookieFlags, /(?:^|;)\s*Secure(?:;|$)/i);
  assert.match(cookieFlags, /(?:^|;)\s*HttpOnly(?:;|$)/i);
  assert.match(cookieFlags, /SameSite=lax/i);
  assert.match(login.headers()["strict-transport-security"] || "", /max-age=31536000/);
  result.checks.push("actual HTTPS login: HSTS and Secure/HttpOnly/SameSite cookie flags");

  for (const kind of ["bundle", "packages"]) {
    const direct = await context.newPage();
    const labelResponse = await direct.goto(new URL(manifest[kind], origin).href, { waitUntil: "networkidle" });
    assert.equal(labelResponse.status(), 200);
    await direct.locator(kind === "bundle" ? "#print-labels" : "button").filter({ hasText: /print|Chop|Печат/i }).first().click();
    assert.equal(await direct.evaluate(() => window.__acceptancePrintCalls), 1, `Direct ${kind} print action must execute`);
    result.printed.push(`direct ${kind}`);
    await direct.close();

    const popupPromise = context.waitForEvent("page");
    await page.evaluate(labelPath => window.acceptanceApi.api.openLabel(labelPath), manifest[kind]);
    const popup = await popupPromise;
    await popup.waitForLoadState("domcontentloaded");
    assert.match(popup.url(), /^blob:https:\/\//, "Current api.openLabel must open its Blob document");
    await popup.locator(kind === "bundle" ? "#print-labels" : "button").filter({ hasText: /print|Chop|Печат/i }).first().click();
    assert.equal(await popup.evaluate(() => window.__acceptancePrintCalls), 1, `Blob ${kind} print action must execute under inherited CSP`);
    const screenshot = path.join(output, `ops09-${kind}-blob.png`);
    await popup.screenshot({ path: screenshot, fullPage: true });
    result.screenshots.push(path.basename(screenshot));
    result.printed.push(`actual api.openLabel blob ${kind}`);
    await popup.close();
  }
  result.checks.push("actual bundle/package direct and Blob print flows");
  assert.deepEqual(errors, [], "Approved hydration must not produce page errors");
  console.log(JSON.stringify({ checks: result.checks, printed: result.printed }));
} finally {
  fs.writeFileSync(path.join(output, "results.json"), JSON.stringify(result, null, 2));
  await browser.close();
}

});
