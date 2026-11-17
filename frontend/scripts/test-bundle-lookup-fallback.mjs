import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Compile the real error module so instanceof exercises the production class.
const errorSource = readFileSync(new URL("../src/lib/errorMessages.ts", import.meta.url), "utf8");
const errorJs = ts.transpileModule(errorSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const errorExports = {};
new Function("exports", errorJs)(errorExports);
const { ApiError } = errorExports;

const sourcePath = process.env.SCANNER_SOURCE || new URL("../src/components/BundleScanPanel.tsx", import.meta.url);
const source = readFileSync(sourcePath, "utf8");
const ast = ts.createSourceFile("BundleScanPanel.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functions = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && ["bundleLookupCandidates", "lookup"].includes(node.name?.text)) functions.push(node.getText(ast));
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(functions.length, 2);
const code = ts.transpile(functions.join("\n"), { target: ts.ScriptTarget.ES2020 });
const scan = "BUNDLE:BND-0001|123456789012|PO:PO-0001";
const bundle = { id: 2 };
async function run(responses) {
  const calls = [];
  const state = { bundle: { id: 99 }, message: "", remembered: [] };
  const env = {
    ApiError, code: scan, includeSewing: false, bandOnly: false,
    setMsg: v => state.message = v, setMessageTone: v => state.tone = v,
    setIsLookingUp: v => state.busy = v, setBundle: v => state.bundle = v,
    setSewingBatch() {}, setCode: v => state.code = v,
    rememberBundle: v => state.remembered.push(v), focusScanInput() {},
    api: { get: async path => { calls.push(path); const result = responses[calls.length - 1]; if (result instanceof Error) throw result; return result; } },
  };
  await new Function(...Object.keys(env), `${code}; return lookup;`)(...Object.values(env))();
  assert.equal(state.busy, false);
  return { calls, state };
}
for (const status of [409, 429, 0, 504, 500]) {
  const error = new ApiError(status, `failure ${status}`);
  const result = await run([new ApiError(404, "missing"), error, bundle]);
  assert.equal(result.calls.length, 2, `status ${status} must stop fallback`);
  assert.equal(result.state.message, error.message);
  assert.equal(result.state.bundle, null);
  assert.deepEqual(result.state.remembered, []);
}
for (const error of [new ApiError(401, "unauthorized"), new ApiError(403, "forbidden"), new Error("unexpected failure")]) {
  const result = await run([error, bundle]);
  assert.equal(result.calls.length, 1);
  assert.equal(result.state.message, error.message);
  assert.equal(result.state.bundle, null);
  assert.deepEqual(result.state.remembered, []);
}
const impostor = Object.assign(new Error("404: missing"), { status: 404 });
assert.equal((await run([impostor, bundle])).calls.length, 1);
const fallback = await run([new ApiError(404, "missing"), bundle]);
assert.equal(fallback.calls.length, 2);
assert.deepEqual(fallback.state.bundle, bundle);
assert.equal(fallback.state.code, "BUNDLE:BND-0001");
assert.equal((await run([bundle])).calls.length, 1);
const failures = Array.from({ length: 6 }, (_, i) => new ApiError(404, `missing ${i}`));
const missing = await run(failures);
assert.equal(missing.calls.length, 6);
assert.equal(missing.state.message, failures[5].message);
assert.ok(missing.calls.every(path => path.startsWith("/api/bundles/lookup?code=")));
console.log("PASS: scanner lookup fallback and decisive errors");
