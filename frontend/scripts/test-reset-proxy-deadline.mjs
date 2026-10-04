import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { TextDecoder, TextEncoder } from "node:util";
import ts from "typescript";

const helperPath = new URL("../src/app/api/auth/reset-proxy.ts", import.meta.url);
const helperContext = { exports: { RESET_PROXY_MAX_BODY_BYTES: 16 * 1024 }, TextDecoder, Uint8Array };
if (fs.existsSync(helperPath)) {
  const helperCode = ts.transpileModule(fs.readFileSync(helperPath, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(helperCode, helperContext);
}
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
    releaseLock: () => {},
    cancel: () => {
      cancelled = true;
      pendingRead?.({ done: true });
      return Promise.resolve();
    },
  };
  const declared = mode === "oversize-header"
    ? String(helperContext.exports.RESET_PROXY_MAX_BODY_BYTES + 1)
    : mode === "oversize-stream" ? "1" : String(bytes.byteLength);
  return {
    json: async () => JSON.parse(rawBody),
    headers: { get: name => name.toLowerCase() === "content-length" ? declared : "attacker-supplied-forwarding-value" },
    body: { getReader: () => reader },
  };
}

for (const route of ["forgot-password", "reset-password"]) {
  const source = fs.readFileSync(new URL(`../src/app/api/auth/${route}/route.ts`, import.meta.url), "utf8");
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const modes = [
    "oversize-header", "oversize-stream", "input-stall", "success", "rejection", "invalid-body", "fetch-stall", "body-stall",
    "invalid-input", "exact-boundary",
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
      assert.deepEqual(Object.keys(requests[0].options.headers), ["Content-Type"], "never forward caller-supplied proxy headers");
      assert.equal(JSON.parse(requests[0].options.body).token, "synthetic");
      if (mode.endsWith("stall")) assert.equal(requests[0].options.signal.aborted, true);
    }
  }
}
console.log("Reset proxies: 20 bounded/deadline handler cases pass; input/upstream stalls, exact size limits, cleanup, errors and no retry.");

// Real streams: enforce bytes even without Content-Length and on split chunks.
const { readBoundedResetJson, RESET_PROXY_MAX_BODY_BYTES: limit } = helperContext.exports;
for (const declared of [null, "1"]) {
  const chunks = [new Uint8Array(limit / 2), new Uint8Array(limit / 2), new Uint8Array(1)];
  let cancelled = false;
  const request = new Request("http://example.test", {
    method: "POST", duplex: "half",
    headers: declared === null ? {} : { "Content-Length": declared },
    body: new ReadableStream({
      pull(controller) { controller.enqueue(chunks.shift()); },
      cancel() { cancelled = true; return Promise.reject(new Error("cancel failed")); },
    }),
  });
  await assert.rejects(readBoundedResetJson(request, new AbortController().signal), error => error.status === 413);
  assert.equal(cancelled, true);
}
for (const declared of ["invalid", "-1", "", "1.5"]) {
  const request = new Request("http://example.test", { method: "POST", body: "{}", headers: { "Content-Length": declared } });
  await assert.rejects(readBoundedResetJson(request, new AbortController().signal), error => error.status === 400);
}
const invalidUtf8 = new Request("http://example.test", { method: "POST", body: new Uint8Array([0xff]) });
await assert.rejects(readBoundedResetJson(invalidUtf8, new AbortController().signal), error => error.status === 400);
console.log("Reset proxy real streams: missing/false lengths, split bytes, cancel rejection and invalid input passed.");
