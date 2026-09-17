// Run the actual scanner lookup with a conflicting response and usable fallback tokens.
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/components/BundleScanPanel.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("BundleScanPanel.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = ["bundleLookupCandidates", "lookup", "manualReceive"];
const functions = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) functions.push(node.getText(ast));
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(functions.length, names.length);
const js = ts.transpile(functions.join("\n"), { target: ts.ScriptTarget.ES2020 });
const scanned = "BUNDLE:BND-0001|123456789012|PO:PO-0001";
const validBundle = { id: 2, bundle_no: "BND-0002", barcode: "123456789012" };

async function run(responses) {
  const calls = [];
  const state = { bundle: { id: 99 }, message: "", tone: "", busy: false, remembered: [], focused: false };
  const env = {
    code: scanned, includeSewing: false,
    setMsg: value => { state.message = value; },
    setMessageTone: value => { state.tone = value; },
    setIsLookingUp: value => { state.busy = value; },
    setBundle: value => { state.bundle = value; }, setSewingBatch() {}, setCode() {},
    rememberBundle: value => state.remembered.push(value),
    focusScanInput: () => { state.focused = true; },
    api: { get: async path => {
      calls.push(path);
      const result = responses[calls.length - 1] ?? validBundle;
      if (result instanceof Error) throw result;
      return result;
    } },
  };
  const lookup = new Function(...Object.keys(env), `${js}; return lookup;`)(...Object.values(env));
  await lookup();
  assert.equal(state.busy, false);
  assert.equal(state.focused, true);
  return { state, calls };
}

// Backend rejects mismatched number/barcode; a later valid token must never be tried.
for (const conflict of [new Error("409: Conflicting bundle references"), Object.assign(new Error("Conflicting bundle references"), { status: 409 })]) {
  const { state, calls } = await run([conflict, validBundle]);
  assert.equal(calls.length, 1);
  assert.equal(state.bundle, null);
  assert.equal(state.tone, "error");
  assert.equal(state.message, conflict.message);
  assert.deepEqual(state.remembered, []);
}

// A conflict discovered after a legacy 404 also blocks the final /barcode fallback.
const conflict = new Error("409: Conflicting bundle references");
const rejected = await run([new Error("404: Bundle not found"), conflict, validBundle]);
assert.equal(rejected.calls.length, 2);
assert.equal(rejected.state.bundle, null);
assert.equal(rejected.state.message, conflict.message);
assert.deepEqual(rejected.state.remembered, []);

// Ordinary missing-token fallback remains available; successful full scans stay single-call.
const fallback = await run([new Error("404: Bundle not found"), validBundle]);
assert.equal(fallback.calls.length, 2);
assert.equal(fallback.state.bundle.id, validBundle.id);
const direct = await run([validBundle]);
assert.equal(direct.calls.length, 1);
assert.equal(direct.state.bundle.id, validBundle.id);
console.log("PASS: bundle QR conflicts stop token/barcode retries, clear stale selection, and preserve ordinary lookup.");

// Exercise the actual manual-receive handler with sibling batches of one order.
const receiptCalls = [];
const busyKeys = [];
const messages = [];
let refreshed = 0;
const receiptEnv = {
  factoryCode: "BST", bundle: null,
  setManualBusyKey: key => busyKeys.push(key), setManualMsg: value => messages.push(value),
  api: { post: async (path, payload) => {
    receiptCalls.push({ path, payload });
    return { received_count: 6, received_quantity: 510, bundle_ids: [2819] };
  } },
  t: (_key, vars) => vars,
  mutateManualOptions: async () => { refreshed++; }, focusScanInput() {},
};
const receive = new Function(...Object.keys(receiptEnv), `${js}; return manualReceive;`)(...Object.values(receiptEnv));
for (const batch of [89, 95, null]) {
  await receive({ production_order_id: 204, production_batch_id: batch, model_id: 5459,
                  order_no: "PO-0182", batch_label: batch === null ? null : `Batch ${batch}` });
}
assert.deepEqual(receiptCalls.map(call => call.payload.production_batch_id), [89, 95, null]);
assert.ok(receiptCalls.every(call => call.path === "/api/bundles/manual-receive-sewing" && call.payload.production_order_id === 204));
assert.equal(new Set(busyKeys.filter(Boolean)).size, 3);
assert.equal(refreshed, 3);
assert.ok(messages.some(message => message?.order === "PO-0182 · Batch 95"));
console.log("PASS: manual receiving submits only the selected batch and keeps sibling row identities distinct.");
