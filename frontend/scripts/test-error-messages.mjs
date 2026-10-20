import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const source = fs.readFileSync("src/lib/errorMessages.ts", "utf8");
const exports = {};
new Function("exports", ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(exports);
const { localizeError, ApiError } = exports;
for (const lang of ["ru", "uz"]) {
  for (const operation of ["Sewing", "Packaging"]) {
    const detail = `${operation} still has unfinished quantities. Continue ${operation.toLowerCase()} the remaining nastils.`;
    assert.notEqual(localizeError(detail, 409, lang), detail);
    assert.notEqual(localizeError(detail, 409, lang), localizeError("Unknown backend detail", 409, lang));
  }
}
// Every warehouse deletion conflict must reach the user with its specific reason.
const deletionSource = fs.readFileSync("../backend/app/services/warehouse_packages.py", "utf8").split("def delete_warehouse_package")[1];
const deletionReasons = [...deletionSource.matchAll(/"((?:Package |Only packages )[^"\n]+)"/g)]
  .map(match => match[1]).filter(reason => reason !== "Package not found");
assert.equal(deletionReasons.length, 17);
for (const lang of ["en", "ru", "uz"]) {
  globalThis.document = { documentElement: { lang } };
  const rendered = deletionReasons.map(reason => {
    const error = new ApiError(409, { detail: reason });
    assert.equal(error.rawDetail, reason);
    assert.notEqual(error.message, new ApiError(409, "Unknown backend detail").message);
    assert.equal(error.message, `409: ${localizeError(reason, 409, lang)}`);
    if (lang !== "en") assert.ok(!error.message.includes(reason));
    return error.message;
  });
  assert.equal(new Set(rendered).size, deletionReasons.length, `${lang} must distinguish each blocker`);
}
assert.match(localizeError("Package is linked to a shipment and cannot be deleted", 409, "uz"), /jo‘natmaga/);
assert.match(localizeError("Package stock is reserved and cannot be deleted", 409, "ru"), /зарезервирован/);
for (const lang of ["en", "ru", "uz"]) {
  for (const code of ["FIRST_GRADE_SIZE_EVIDENCE_REQUIRED", "FIRST_GRADE_SIZE_EXCEEDED", "FIRST_GRADE_ONE_PIECE_REQUIRED", "SHIPMENT_DELETE_BEFORE_DISPATCH", "SHIPMENT_ALREADY_DELETED"]) {
    const message = localizeError(code, 409, lang);
    assert.ok(message.length > 15 && !message.includes(code), `${code} must have a ${lang} message`);
  }
}
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

for (const lang of ["ru", "uz"]) {
  globalThis.document.documentElement.lang = lang;
  const error = new ApiError(422, { detail: [{ loc: ["body", "report_date"], msg: "Field required" }] });
  assert.equal(error.rawDetail, "report date: Field required");
  assert.ok(!error.message.includes("Field required"));
  for (const message of ["Could not load HR data.", "Select a brand for the production order.", "Select an available fabric batch for the cutting team.", "Enter estimated material amount greater than zero."]) {
    assert.notEqual(localizeError(message), message);
    assert.notEqual(localizeError(message), localizeError("Unknown backend detail"));
  }
  for (const code of ["fabricScans.roll_not_found", "ecoTransfers.alreadySent", "sewingEdit.stale"]) {
    const coded = new ApiError(409, { detail: code });
    assert.equal(coded.rawDetail, code);
    assert.ok(!coded.message.includes(code));
  }
}
const apiExports = {};
new Function("exports", "require", ts.transpile(fs.readFileSync("src/lib/api.ts", "utf8"), { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(apiExports, () => exports);
const originalFetch = globalThis.fetch;
try {
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  globalThis.document.documentElement.lang = "ru";
  await assert.rejects(apiExports.fetchResponse("/report.xlsx"), /Нет связи/);
  globalThis.document.documentElement.lang = "uz";
  await assert.rejects(apiExports.fetchResponse("/report.xlsx"), /aloqa/);
  const abort = new DOMException("Cancelled", "AbortError");
  globalThis.fetch = async () => { throw abort; };
  await assert.rejects(apiExports.fetchResponse("/report.xlsx"), error => error === abort);
} finally { globalThis.fetch = originalFetch; }
console.log("Structured validation, client validation, preserved codes and download network error checks passed.");
