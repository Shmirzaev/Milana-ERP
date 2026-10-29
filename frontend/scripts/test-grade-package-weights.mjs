import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";
const exports = {};
vm.runInNewContext(ts.transpileModule(fs.readFileSync("src/lib/gradePackageWeights.ts", "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText, { exports });
const { gradePackageWeights: allocate } = exports;
const rows = [{ size: "S", quantity: 3 }, { size: "M", quantity: 2 }];
const unitSum = packs => packs.reduce((sum, pack) => sum + Math.round(pack.weight_kg * 10000), 0);
const first = allocate("first_grade", rows, "1.0001");
assert.equal(first.length, 5);
assert.equal(unitSum(first), 10001);
assert.ok(first.every(pack => pack.quantity === 1 && pack.weight_kg > 0));
const second = allocate("second_grade", rows, "1.0001");
assert.equal(second.length, 2);
assert.equal(second[0].weight_kg, 0.6001);
assert.equal(second[1].weight_kg, 0.4);
assert.equal(unitSum(second), 10001);
for (const value of ["", "0", "-1", "Infinity", "NaN", "1e2", "0.00001", "10000000000", "0.0001"]) {
  assert.throws(() => allocate("first_grade", rows, value), value);
}
for (const quantity of [0, -1, 1.2, Infinity, 201]) assert.throws(() => allocate("first_grade", [{ size: "S", quantity }], "10"));
// Deterministic bounded precision/integrity challenge, 1,000 allocations.
for (let i = 1; i <= 500; i++) {
  const sizes = [{ size: "S", quantity: i % 83 + 1 }, { size: "M", quantity: i % 97 + 1 }];
  const kg = `${i}.${String(i * 19 % 10000).padStart(4, "0")}`;
  for (const grade of ["first_grade", "second_grade"]) {
    const packs = allocate(grade, sizes, kg);
    assert.equal(unitSum(packs), i * 10000 + i * 19 % 10000);
    assert.equal(packs.reduce((sum, pack) => sum + pack.quantity, 0), sizes[0].quantity + sizes[1].quantity);
    assert.ok(packs.every(pack => pack.weight_kg > 0));
  }
}
console.log("Grade weights: exact totals, proportional shares, refusals and 1,000 bounded allocations passed.");
