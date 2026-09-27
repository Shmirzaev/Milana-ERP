import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/salesOrderMoney.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const exports = {};
new Function("exports", output)(exports);

assert.equal(exports.recordedSalesOrderMoney(125, "UZS"), "125.00 UZS");
assert.equal(exports.recordedSalesOrderMoney(125, null), "—");
assert.equal(exports.recordedSalesOrderMoney(null, "USD"), "—");
assert.equal(exports.recordedSalesOrderMoney(undefined, undefined), "—");
console.log("Sales-order amounts require a recorded amount and currency.");
