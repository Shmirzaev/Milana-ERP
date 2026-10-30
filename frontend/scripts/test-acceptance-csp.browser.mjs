// SEC09: run against an isolated production Next + Nginx TLS + fixture backend.
// Fixture setup uses fixtures/acceptance_csp_backend.py; never point at production.
import assert from "node:assert/strict";
import fs from "node:fs";
import https from "node:https";
import path from "node:path";
import { isIP } from "node:net";
import test from "node:test";

const origin = new URL(process.env.ACCEPTANCE_CSP_URL || "https://127.0.0.1:18443");
assert.equal(origin.protocol, "https:", "The closing test requires real TLS");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(origin.hostname), "Isolated loopback target only");
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
