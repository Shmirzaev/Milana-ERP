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

// The server commits, its response is lost, and the session then expires.
// Auth failure must not discard the original request or mint a replacement key.
let stockMovements = 0;
const savedResponses = new Map();
function serverReceive(body, loggedIn, loseResponse = false) {
  if (!loggedIn) return {status: 401};
  if (!savedResponses.has(body.request_key)) {
    stockMovements++;
    savedResponses.set(body.request_key, {movement_id: stockMovements});
  }
  return loseResponse ? {status: 0} : {status: 200, result: savedResponses.get(body.request_key)};
}
exports.saveEcoPendingAttempt(key, request);
const lostSuccess = serverReceive(request.body, true, true);
assert.equal(exports.retainEcoPendingAfterFailure(key, lostSuccess.status, false), true);
const unauthorized = serverReceive(exports.loadEcoPendingAttempt(key).body, false);
assert.equal(exports.retainEcoPendingAfterFailure(key, unauthorized.status, true), true);
const restoredAfterLogin = exports.loadEcoPendingAttempt(key);
assert.equal(JSON.stringify(restoredAfterLogin), JSON.stringify(request));
assert.equal(serverReceive(restoredAfterLogin.body, true).result.movement_id, 1);
assert.equal(stockMovements, 1);
exports.saveEcoPendingAttempt(key, null);

for (const status of [401, 403, 408, 429, 500, 502, 503, 504, 0]) {
  exports.saveEcoPendingAttempt(key, request);
  assert.equal(exports.retainEcoPendingAfterFailure(key, status, false), true);
  assert.equal(exports.loadEcoPendingAttempt(key).body.request_key, "same-key");
}
for (const status of [400, 404, 409, 422]) {
  exports.saveEcoPendingAttempt(key, request);
  assert.equal(exports.retainEcoPendingAfterFailure(key, status, false), false);
  assert.equal(exports.loadEcoPendingAttempt(key), null);
  exports.saveEcoPendingAttempt(key, request);
  assert.equal(exports.retainEcoPendingAfterFailure(key, status, true), true);
  assert.equal(exports.loadEcoPendingAttempt(key).body.request_key, "same-key");
}
storage.set(key, "broken-json");
assert.equal(exports.loadEcoPendingAttempt(key), null);

const english = exports.ecoInventoryText("en");
for (const language of ["ru", "uz"]) {
  const translated = exports.ecoInventoryText(language);
  assert.deepEqual(Object.keys(translated).sort(), Object.keys(english).sort());
  assert.notEqual(translated.fabric, english.fabric);
}
console.log("Eco material decimal, retry-recovery and translation checks passed.");
