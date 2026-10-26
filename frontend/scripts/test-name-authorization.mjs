import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

function loadModule(path, dependencies = {}) {
  const source = fs.readFileSync(new URL(path, import.meta.url), "utf8");
  const exports = {};
  new Function("exports", "require", ts.transpile(source, {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
  }))(exports, (name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  });
  return exports;
}

const access = loadModule("../src/lib/access.ts");
const { isAbbosbekPricingUser: canPurchase, isAccessoryPricingUser: canPriceAccessories } = loadModule(
  "../src/lib/priceCalculationRequests.ts", { "@/lib/access": access },
);
const base = { name: "Ordinary employee", email: "ordinary@example.com", role: "Purchaser", permissions: [] };
assert.equal(canPurchase(undefined), false);
for (const access_configured of [false, true]) {
  for (const identity of [
    { name: "Abbosbek" },
    { name: "  aBbOsBeK   Employee  " },
    { email: "abbosbek@example.com" },
    { email: "ABBOSBEK@example.com" },
  ]) {
    for (const role of ["Purchaser", "Admin", "Management", "Super Admin"]) {
      const user = { ...base, ...identity, role, access_configured };
      assert.equal(canPurchase(user), false, "Profile identity and role labels must not grant pricing access");
      for (const permission of ["*", "price_calculation.purchasing"]) {
        assert.equal(canPurchase({ ...user, permissions: [permission] }), true, "Preserve explicit effective grants");
      }
      assert.equal(canPurchase({ ...user, permissions: ["purchasing.view"] }), false);
    }
  }
}
assert.equal(canPurchase({
  ...base, factory_code: "ECO", assigned_factory_code: "MIL", permissions: ["purchasing.view"],
}), false, "Primary-factory role labels cannot replace selected-factory permissions");
assert.equal(canPurchase({
  ...base, factory_code: "ECO", permissions: ["price_calculation.purchasing"],
}), true);
assert.equal(canPurchase({
  permissions: [],
  get name() { throw new Error("Authorization must not inspect display name"); },
  get email() { throw new Error("Authorization must not inspect mutable email"); },
}), false);
assert.equal(canPriceAccessories({ ...base, department_code: "STR", permissions: ["storage.items"] }), true);
assert.equal(canPriceAccessories({ ...base, access_configured: true, department_code: "STR", permissions: ["storage.items"] }), false);
console.log("Name authorization checks passed");
