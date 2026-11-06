import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync("src/lib/gradePackageWeights.ts", "utf8");
function allocator(code) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, { exports });
  return exports.gradePackageWeights;
}
function verify(allocate) {
  const rows = [{ size: "unused", quantity: 0 }, { size: "S", quantity: 2 }, { size: "L", quantity: 3 }];
  for (const grade of ["first_grade", "second_grade"]) {
    const packs = Array.from(allocate(grade, rows, " 0.0013 "));
    assert.equal(packs.length, grade === "first_grade" ? 5 : 2);
    assert.equal(packs.reduce((sum, row) => sum + row.quantity, 0), 5);
    assert.equal(packs.reduce((sum, row) => sum + Math.round(row.weight_kg * 10000), 0), 13);
    assert.ok(packs.every(row => row.quantity > 0 && row.weight_kg >= 0.0001 && row.size !== "unused"));
    assert.deepEqual(packs.map(row => Math.round(row.weight_kg * 10000)), grade === "first_grade" ? [3, 3, 3, 2, 2] : [6, 7]);
    assert.deepEqual(packs.map(row => row.quantity), grade === "first_grade" ? [1, 1, 1, 1, 1] : [2, 3]);
    for (const value of ["0.0004", "0", "-1", "0.00101", "1e1", "NaN", "Infinity", "10000000000", ""]) assert.throws(() => allocate(grade, rows, value), /weight/);
    for (const quantity of [-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) assert.throws(() => allocate(grade, [{ size: "S", quantity }], "1"), /quantity/);
    assert.throws(() => allocate(grade, [], "1"), /quantity/);
    assert.throws(() => allocate(grade, [{ size: "S", quantity: 0 }], "1"), /quantity/);
  }
  const exactMinimum = Array.from(allocate("first_grade", [{ size: "S", quantity: 200 }], "0.02"));
  assert.equal(exactMinimum.length, 200);
  assert.ok(exactMinimum.every(row => row.weight_kg === 0.0001));
  assert.throws(() => allocate("first_grade", [{ size: "S", quantity: 201 }], "1"), /quantity/);
  const sizes = Array.from({ length: 200 }, (_, i) => ({ size: String(i), quantity: 2 }));
  assert.equal(allocate("second_grade", sizes, "1").length, 200);
  assert.throws(() => allocate("second_grade", [...sizes, { size: "extra", quantity: 1 }], "1"), /quantity/);
  const bulk = allocate("second_grade", [{ size: "S", quantity: 1000000 }], "100");
  assert.equal(bulk.length, 1); assert.equal(bulk[0].quantity, 1000000); assert.equal(bulk[0].weight_kg, 100);
  const maximum = allocate("second_grade", [{ size: "S", quantity: 1 }], "9999999999.9999");
  assert.equal(Math.round(maximum[0].weight_kg * 10000), 99999999999999);
}
verify(allocator(source));
const faults = [
  ["lost remainder", "let remaining = units % pieces;", "let remaining = 0;"],
  ["rounded quotient", "Math.floor(units / pieces)", "Math.round(units / pieces)"],
  ["zero-weight labels", "if (units < pieces)", "if (units < 0)"],
  ["package cap widened", "count > 200", "count > 201"],
  ["precision widened", "{1,4}", "{1,5}"],
  ["first-grade count", 'grade === "first_grade" ? 1 : row.quantity', 'grade === "first_grade" ? 2 : row.quantity'],
  ["duplicate remainder", "remaining -= extra;", "remaining -= 0;"],
  ["wrong output precision", "weight_kg: (perPiece * quantity + extra) / 10000", "weight_kg: (perPiece * quantity + extra) / 1000"],
];
for (const [name, before, after] of faults) {
  assert.ok(source.includes(before), `${name}: mutation must match actual source`);
  assert.throws(() => verify(allocator(source.replace(before, after))), `${name}: independent business assertions must reject fault`);
}
console.log(`Grade weight independent boundaries and ${faults.length} deliberate faults passed.`);
