import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const errorExports = {};
const apiExports = {};
new Function("exports", ts.transpile(fs.readFileSync(new URL("../src/lib/errorMessages.ts", import.meta.url), "utf8"), {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
}))(errorExports);
new Function("exports", "require", ts.transpile(fs.readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8"), {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
}))(apiExports, () => errorExports);

const { api } = apiExports;
const originalFetch = globalThis.fetch;
const detail = "Authentication is temporarily unavailable. Try again later.";
try {
  for (const [name, call] of [
    ["login", () => api.login("test@example.invalid", "test", "MIL")],
    ["forgot", () => api.forgotPassword("test@example.invalid")],
    ["reset", () => api.resetPassword("test-token", "test-password", "test-password")],
  ]) {
    let requests = 0;
    globalThis.fetch = async () => {
      requests++;
      return Response.json({ detail }, { status: 503 });
    };
    await assert.rejects(call(), error => {
      assert.equal(error.status, 503, name);
      assert.equal(error.message, `503: ${detail}`, name);
      return true;
    });
    assert.equal(requests, 1, `${name}: a definite 503 must be shown after one request`);
  }

  let requests = 0;
  globalThis.fetch = async () => {
    requests++;
    if (requests < 3) throw new TypeError("Failed to fetch");
    return Response.json({ ok: true });
  };
  await api.login("test@example.invalid", "test", "MIL");
  assert.equal(requests, 3, "genuine network failures still retry");
} finally {
  globalThis.fetch = originalFetch;
}
console.log("Auth 503: login, forgot and reset respond once; network retry preserved.");
