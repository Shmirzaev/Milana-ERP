import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

// Execute the same helpers used by the sidebar and route guard.
const exports = {};
const compiled = ts.transpileModule(fs.readFileSync("src/lib/priceCalculationRequests.ts", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
vm.runInNewContext(compiled, { exports, require: () => ({ isMaterialsOnly: () => false }) });
for (const access_configured of [false, true]) {
  for (const [name, email] of [["Abbosbek", "ordinary@example.com"], ["Abbosbek Synthetic", "ordinary@example.com"], ["Ordinary", "abbosbek@example.com"]]) {
    const me = { name, email, access_configured, permissions: [] };
    assert.equal(exports.isPurchasingPricingUser(me), false);
    for (const permission of ["*", "price_calculation.purchasing"]) {
      assert.equal(exports.isPurchasingPricingUser({ ...me, permissions: [permission] }), true);
    }
  }
}
assert.equal(exports.isPurchasingPricingUser(undefined), false);
console.log("Purchasing pricing visibility requires server-resolved grants, regardless of profile identity.");
