import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

for (const route of ["forgot-password", "reset-password"]) {
  const source = fs.readFileSync(new URL(`../src/app/api/auth/${route}/route.ts`, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  for (const mode of ["success", "rejection", "invalid-body", "fetch-stall", "body-stall", "invalid-input"]) {
    const timers = new Set();
    const requests = [];
    const stalled = signal => new Promise((_resolve, reject) => {
      if (signal?.aborted) reject(new Error("aborted"));
      else signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    });
    const context = {
      exports: {}, AbortController,
      process: { env: { NODE_ENV: "development", API_URL: "http://127.0.0.1:9" } },
      require: name => {
        assert.equal(name, "next/server");
        return { NextResponse: { json: (body, options) => ({ body, status: options.status }) } };
      },
      setTimeout: (callback, delay) => {
        assert.equal(delay, 15_000);
        const timer = setTimeout(callback, 5);
        timers.add(timer);
        return timer;
      },
      clearTimeout: timer => { timers.delete(timer); clearTimeout(timer); },
      fetch: async (url, options) => {
        requests.push({ url, options });
        if (mode === "fetch-stall") return stalled(options.signal);
        return {
          status: mode === "rejection" ? 429 : 200,
          statusText: "Upstream response",
          json: async () => {
            if (mode === "body-stall") return stalled(options.signal);
            if (mode === "invalid-body") throw new Error("Invalid upstream JSON");
            return { message: "unchanged" };
          },
        };
      },
    };
    vm.runInNewContext(code, context);
    let watchdog;
    const result = await Promise.race([
      context.exports.POST({ json: async () => {
        if (mode === "invalid-input") throw new Error("Invalid request JSON");
        return { token: "synthetic", email: "test@example.test" };
      } }),
      new Promise(resolve => { watchdog = setTimeout(() => resolve("hung"), 150); }),
    ]);
    clearTimeout(watchdog);
    assert.notEqual(result, "hung", `${route}/${mode}: upstream request exceeded deadline`);
    assert.equal(result.status, mode.endsWith("stall") ? 503 : mode === "rejection" ? 429 : mode === "invalid-input" ? 400 : 200);
    assert.equal(timers.size, 0, `${route}/${mode}: deadline timer leaked`);
    if (mode === "invalid-input") assert.equal(requests.length, 0);
    else {
      assert.equal(requests.length, 1, "reset requests must never automatically retry");
      assert.equal(requests[0].url, `http://127.0.0.1:9/api/auth/${route}`);
      assert.equal(requests[0].options.cache, "no-store");
      assert.equal(JSON.parse(requests[0].options.body).token, "synthetic");
      if (mode.endsWith("stall")) assert.equal(requests[0].options.signal.aborted, true);
    }
  }
}
console.log("Reset proxies: 12 handler cases pass; fetch/body deadlines, cleanup, errors and no automatic retry.");
