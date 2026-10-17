import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const helperSource = fs.readFileSync("src/lib/shipmentScan.ts", "utf8");
const compiled = ts.transpile(helperSource, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 });
const helper = { exports: {} };
new Function("exports", compiled)(helper.exports);
const { previousShipmentScanMessage, successfulShipmentScanMessage } = helper.exports;
const result = {
  sign: "warning", message: "Already scanned", package_no: "PKG-0001",
  previous_scan: {
    shipment_no: "SH-0001", customer_name: "Customer One", scanned_by_name: "First Operator",
    scanned_at: "2026-10-14T03:04:05Z",
  },
};
for (const lang of ["en", "ru", "uz"]) {
  const message = previousShipmentScanMessage(result, lang);
  for (const value of ["PKG-0001", "SH-0001", "Customer One", "First Operator", "08:04:05", "2026", "UTC+05:00"]) {
    assert.ok(message.includes(value), `${lang}: missing ${value}`);
  }
  const missing = previousShipmentScanMessage({ ...result, previous_scan: { ...result.previous_scan, customer_name: null, scanned_by_name: null, scanned_at: "invalid" } }, lang);
  assert.ok(!/undefined|null|Invalid Date/.test(missing));
}
assert.equal(previousShipmentScanMessage({ sign: "success" }, "en"), null);

// Execute the actual page handler so warnings cannot silently become generic success.
const source = fs.readFileSync("src/app/(app)/shipments/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let handler;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === "scanPackage") handler = node.getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast);
assert.ok(handler);
for (const sign of ["warning", "error", "success"]) {
  const state = { error: "old error", warning: "old warning", message: "old message", code: "old", refreshes: 0 };
  const env = {
    shipmentId: 1, scanCode: "PKG-0001", lang: "en", previousShipmentScanMessage, successfulShipmentScanMessage,
    api: { post: async () => sign === "success" ? { sign, package_no: "PKG-0001", package_quantity: 60 } : { ...result, sign } },
    setError: v => { state.error = v; }, setMessage: v => { state.message = v; },
    setScanWarning: v => { state.warning = v; }, setScanCode: v => { state.code = v; },
    refresh: async () => { state.refreshes++; }, localizeError: v => v, t: v => v,
    errorMessage: e => e.message,
  };
  await new Function(...Object.keys(env), `${ts.transpile(handler, { target: ts.ScriptTarget.ES2020 })}; return scanPackage;`)(...Object.values(env))();
  assert.equal(state.refreshes, 1);
  assert.equal(state.code, "");
  if (sign === "success") {
    assert.equal(state.message, "PKG-0001 · 60 pieces scanned.");
    assert.equal(state.error, "");
    assert.equal(state.warning, "");
  } else {
    assert.equal(state.message, "");
    assert.ok(state[sign === "warning" ? "warning" : "error"].includes("Customer One"));
    assert.ok(state[sign === "warning" ? "warning" : "error"].includes("08:04:05"));
  }
}
console.log("Shipment duplicate scan messages and handler passed (EN/RU/UZ).");

for (const lang of ["en", "ru", "uz"]) {
  assert.ok(successfulShipmentScanMessage({ sign: "success", package_no: "PKG-0002", package_quantity: 24 }, lang).includes("24"));
  for (const sign of ["warning", "error"]) assert.equal(successfulShipmentScanMessage({ sign, package_quantity: 60 }, lang), null);
  for (const package_quantity of [undefined, null, NaN, -1]) assert.equal(successfulShipmentScanMessage({ sign: "success", package_quantity }, lang), null);
}
assert.equal(successfulShipmentScanMessage({ sign: "success", package_quantity: 1 }, "en"), "1 piece scanned.");
