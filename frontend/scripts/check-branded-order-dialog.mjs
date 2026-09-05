import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const runtime = fs.readFileSync("src/lib/i18n.tsx", "utf8");
const keys = [
  "cutting.not_started", "cutting.partial", "cutting.completed", "modelNumber",
  "searchModelNumber", "variantNumber", "selectVariant", "noApprovedVariants", "modelLoadFailed",
];
for (const lang of ["en", "ru", "uz"]) {
  const path = `src/lib/i18n/locales/${lang}-supplemental.ts`;
  assert(runtime.includes(`./i18n/locales/${lang}-supplemental`), `${lang} must be loaded by the runtime`);
  const source = fs.readFileSync(path, "utf8");
  const exports = {};
  vm.runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS }), { exports });
  for (const suffix of keys) {
    const key = `page.planning.${suffix}`;
    assert.equal(typeof exports.default[key], "string", `${lang}: missing runtime translation ${key}`);
    assert(exports.default[key].trim() && exports.default[key] !== key);
  }
}
console.log("Branded order dialog runtime translations passed.");
