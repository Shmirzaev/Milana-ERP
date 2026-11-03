import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(new URL("../src/lib/ecoInventory.ts", import.meta.url), "utf8");
const exports = {};
const storage = new Map();
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
  exports,
  sessionStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
});

// Complete a partial receipt without the binary-float 1.3 - 0.1 < 1.2 trap.
assert.equal(exports.fabricTransferOutstanding({quantity: "1.3000", received_quantity: "0.1000"}), 1.2);
assert.equal(exports.fabricTransferOutstanding({quantity: "9999999999.9999", received_quantity: "9999999999.9998"}), 0.0001);
assert.equal(exports.fabricTransferOutstanding({quantity: "12.5000", received_quantity: "12.5000"}), 0);

// Restoring an uncertain request preserves its exact key AND decimal payload.
const key = "milana:eco-inventory:pending:1:ECO";
const request = {endpoint: "/api/eco-inventory/receive", body: {request_key: "same-key", quantity: "12.5000"}};
exports.saveEcoPendingAttempt(key, request);
assert.equal(JSON.stringify(exports.loadEcoPendingAttempt(key)), JSON.stringify(request));
assert.equal(exports.loadEcoPendingAttempt("milana:eco-inventory:pending:2:ECO"), null);
exports.saveEcoPendingAttempt(key, null);
assert.equal(exports.loadEcoPendingAttempt(key), null);
storage.set(key, "broken-json");
assert.equal(exports.loadEcoPendingAttempt(key), null);

const english = exports.ecoInventoryText("en");
for (const language of ["ru", "uz"]) {
  const translated = exports.ecoInventoryText(language);
  assert.deepEqual(Object.keys(translated).sort(), Object.keys(english).sort());
  assert.notEqual(translated.fabric, english.fabric);
}
console.log("Eco material decimal, retry-recovery and translation checks passed.");
