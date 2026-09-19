import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const source = fs.readFileSync("src/lib/errorMessages.ts", "utf8");
const exports = {};
new Function("exports", ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(exports);
const { localizeError, ApiError } = exports;
assert.match(localizeError("Package not found", 404, "ru"), /Упаковка/);
assert.match(localizeError("Package not found", 404, "uz"), /Qadoq/);
assert.equal(localizeError("Package not found", 404, "en"), "Package not found");
assert.match(localizeError("Package PKG-009 belongs to another sales order.", 400, "ru"), /PKG-009.*другому/);
assert.match(localizeError("Package PKG-009 is already attached to shipment SH-002.", 409, "uz"), /PKG-009.*SH-002/);
for (const lang of ["ru", "uz"]) {
  globalThis.document = { documentElement: { lang } };
  const err = new ApiError(409, "Unknown backend detail");
  assert.equal(err.status, 409);
  assert.equal(err.rawDetail, "Unknown backend detail");
  assert.ok(err.message.startsWith("409:"));
  assert.ok(!err.message.includes("Unknown backend detail"));
}
globalThis.document.documentElement.lang = "ru";
assert.match(new ApiError(0, "Failed to fetch").message, /Нет связи/);
globalThis.document.documentElement.lang = "uz";
assert.match(new ApiError(504, "Request timed out").message, /vaqtida/);
console.log("Error locale, fallback, machine-status and language-switch checks passed.");
