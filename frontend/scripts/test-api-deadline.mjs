import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const exports = {};
const errorExports = {};
new Function("exports", ts.transpile(fs.readFileSync(new URL("../src/lib/errorMessages.ts", import.meta.url), "utf8"), { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(errorExports);
new Function("exports", "require", ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(exports, () => errorExports);
const { api } = exports;
const originalFetch = globalThis.fetch;
try {
  // Real Response + abort-aware body: headers arrive immediately, body never ends.
  for (const status of [200, 503]) {
    let aborted = false;
    globalThis.fetch = async (_url, { signal }) => new Response(new ReadableStream({
      start(controller) {
        signal.addEventListener("abort", () => {
          aborted = true;
          controller.error(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      },
    }), { status, headers: { "Content-Type": "application/json" } });
    for (const invoke of [() => api.get("/test", 15), () => api.postForm("/test", new FormData(), 15)]) {
      aborted = false;
      const outcome = await Promise.race([
        invoke().then(() => "resolved", error => error.message),
        new Promise(resolve => setTimeout(() => resolve("hung"), 150)),
      ]);
      assert.notEqual(outcome, "hung", "deadline must include response body consumption");
      assert.match(outcome, /504:/);
      assert.equal(aborted, true);
    }
  }
  globalThis.fetch = async () => Response.json({ ok: true });
  assert.deepEqual(await api.get("/test", 20), { ok: true });
  globalThis.fetch = async () => new Response(null, { status: 204 });
  assert.equal(await api.del("/test"), undefined);
  globalThis.fetch = async () => Response.json({ detail: [{ loc: ["body", "quantity"], msg: "must be positive" }] }, { status: 422 });
  await assert.rejects(api.post("/test", {}), /422:/);
  const caller = new AbortController();
  globalThis.fetch = async (_url, { signal }) => new Response(new ReadableStream({ start(controller) {
    signal.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), { once: true });
  } }));
  const request = api.getWithSignal("/test", caller.signal, 1000);
  setTimeout(() => caller.abort(), 5);
  await assert.rejects(request, error => error.name === "AbortError");
  // Cover fixed-timeout callers with accelerated timers; successful headers
  // must not allow a stalled body to escape the deadline either.
  const originalSetTimeout = globalThis.setTimeout;
  try {
    globalThis.setTimeout = (callback, delay, ...args) => originalSetTimeout(callback, Math.min(delay, 10), ...args);
    for (const [name, invoke, status] of [
      ["login", () => api.login("synthetic@example.test", "synthetic", "MIL"), 401],
      ["forgot", () => api.forgotPassword("synthetic@example.test"), 200],
      ["reset", () => api.resetPassword("synthetic", "synthetic", "synthetic"), 200],
      ["label", () => api.openLabel("/test"), 200],
      ["logout", () => api.logout(), 200],
    ]) {
      let aborted = false;
      globalThis.fetch = async (_url, { signal }) => new Response(new ReadableStream({
        start(controller) {
          signal.addEventListener("abort", () => {
            aborted = true;
            controller.error(new DOMException("Aborted", "AbortError"));
          }, { once: true });
        },
      }), { status, headers: { "Content-Type": "application/json" } });
      const result = await Promise.race([
        invoke().then(() => "resolved", error => error.message),
        new Promise(resolve => originalSetTimeout(() => resolve("hung"), 300)),
      ]);
      assert.notEqual(result, "hung", name);
      assert.equal(aborted, true, name);
      if (name !== "logout") assert.match(result, /50[34]:/, name);
    }
  } finally {
    globalThis.setTimeout = originalSetTimeout;
  }
  console.log("API deadlines: JSON/form/error bodies bounded; cancellation and normal responses preserved.");
} finally {
  globalThis.fetch = originalFetch;
}
