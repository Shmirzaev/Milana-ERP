import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(path) {
  const exports = {};
  const compiled = ts.transpileModule(fs.readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  vm.runInNewContext(compiled, { exports, module: { exports } });
  return exports;
}
const { changeAccess, accessText } = load("src/lib/userAccess.ts");
const { isSewingRole } = load("src/lib/access.ts");
let value = { MIL: { allow: ["finance.view"], deny: ["sales.orders"] } };
const original = JSON.stringify(value);
value = changeAccess(value, "ECO", "cutting.records", "allow");
assert.equal(JSON.stringify(value.MIL), JSON.stringify(JSON.parse(original).MIL));
value = changeAccess(value, "MIL", "sales.orders", "allow");
assert.equal(value.MIL.deny.includes("sales.orders"), false);
assert.equal(value.MIL.allow.includes("sales.orders"), true);
value = changeAccess(value, "MIL", "sales.orders", "deny");
assert.equal(value.MIL.allow.includes("sales.orders"), false);
value = changeAccess(value, "MIL", "sales.orders", "default");
assert.equal(value.MIL.deny.includes("sales.orders"), false);
assert.equal(value.ECO.allow[0], "cutting.records");
assert.equal(isSewingRole({ role: "Sewing", permissions: ["sewing.workspace"] }), true);
assert.equal(isSewingRole({ role: "Sewing", access_configured: true, permissions: ["finance.view"] }), false);
for (const language of ["en", "ru", "uz"]) {
  const text = accessText(language);
  assert.ok(text.title && text.allow && text.deny && text.inherit && text.scopeHelp);
  assert.equal(Object.keys(text.groups).length, 20);
}
console.log("User access: allow/deny/default, factory isolation, legacy and configured Sewing, and EN/RU/UZ labels passed.");
