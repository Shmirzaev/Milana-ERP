import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { TextDecoder, TextEncoder } from "node:util";
import ts from "typescript";

const helperSource = fs.readFileSync(
  new URL("../src/app/api/auth/reset-proxy.ts", import.meta.url),
  "utf8",
);
const helperCode = ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const helperContext = { exports: {}, TextDecoder, Uint8Array };
vm.runInNewContext(helperCode, helperContext);
const encoder = new TextEncoder();

function requestFor(mode) {
  const ordinary = JSON.stringify({ token: "synthetic", email: "test@example.test" });
  const exactPrefix = '{"token":"synthetic","email":"test@example.test","padding":"';
  const exactSuffix = '"}';
  const exactBoundary = exactPrefix
    + "x".repeat(helperContext.exports.RESET_PROXY_MAX_BODY_BYTES - encoder.encode(exactPrefix + exactSuffix).byteLength)
    + exactSuffix;
  const rawBody = mode === "invalid-input"
    ? "{"
    : mode === "oversize-stream"
      ? JSON.stringify({ padding: "x".repeat(helperContext.exports.RESET_PROXY_MAX_BODY_BYTES) })
      : mode === "exact-boundary"
        ? exactBoundary
      : ordinary;
  const bytes = encoder.encode(rawBody);
  let delivered = false;
  let pendingRead;
  let cancelled = false;
  const reader = {
    read: () => {
      if (mode === "input-stall" && !cancelled) {
        return new Promise(resolve => { pendingRead = resolve; });
      }
      if (delivered || cancelled) return Promise.resolve({ done: true });
      delivered = true;
      return Promise.resolve({ done: false, value: bytes });
    },
    cancel: () => {
      cancelled = true;
      pendingRead?.({ done: true });
      return Promise.resolve();
    },
  };
  const declared = mode === "oversize-header"
    ? String(helperContext.exports.RESET_PROXY_MAX_BODY_BYTES + 1)
    : String(bytes.byteLength);
  return {
    headers: { get: name => name.toLowerCase() === "content-length" ? declared : null },
    body: { getReader: () => reader },
  };
}

for (const route of ["forgot-password", "reset-password"]) {
  const source = fs.readFileSync(new URL(`../src/app/api/auth/${route}/route.ts`, import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const modes = [
    "success", "rejection", "invalid-body", "fetch-stall", "body-stall",
    "invalid-input", "exact-boundary", "oversize-header", "oversize-stream", "input-stall",
  ];
  for (const mode of modes) {
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
        if (name === "next/server") {
          return { NextResponse: { json: (body, options) => ({ body, status: options.status }) } };
        }
        assert.equal(name, "../reset-proxy");
        return helperContext.exports;
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
      context.exports.POST(requestFor(mode)),
      new Promise(resolve => { watchdog = setTimeout(() => resolve("hung"), 150); }),
    ]);
    clearTimeout(watchdog);
    assert.notEqual(result, "hung", `${route}/${mode}: request exceeded deadline`);
    const expectedStatus = mode.endsWith("stall")
      ? mode === "input-stall" ? 408 : 503
      : mode.startsWith("oversize")
        ? 413
        : mode === "rejection"
          ? 429
          : mode === "invalid-input"
            ? 400
            : 200;
    assert.equal(result.status, expectedStatus, `${route}/${mode}`);
    assert.equal(timers.size, 0, `${route}/${mode}: deadline timer leaked`);
    if (["invalid-input", "oversize-header", "oversize-stream", "input-stall"].includes(mode)) {
      assert.equal(requests.length, 0);
    } else {
      assert.equal(requests.length, 1, "reset requests must never automatically retry");
      assert.equal(requests[0].url, `http://127.0.0.1:9/api/auth/${route}`);
      assert.equal(requests[0].options.cache, "no-store");
      assert.equal(JSON.parse(requests[0].options.body).token, "synthetic");
      if (mode.endsWith("stall")) assert.equal(requests[0].options.signal.aborted, true);
    }
  }
}
console.log("Reset proxies: 20 bounded/deadline handler cases pass; input/upstream stalls, exact size limits, cleanup, errors and no retry.");
