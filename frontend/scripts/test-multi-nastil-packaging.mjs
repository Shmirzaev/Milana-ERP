import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const library = {};
new Function("exports", ts.transpileModule(fs.readFileSync(new URL("../src/lib/multiNastilPackaging.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(library);
const { planSelectedNastils } = library;
const items = [{ model_id: 1, color: "White", size: "M", quantity: 60 }];
const sources = [{ id: 1, label: "Nastil A", available: 35 }, { id: 2, label: "Nastil B", available: 40 },
  { id: 3, label: "Unselected", available: 90 }, { id: 4, label: "Still sewing", available: 0 }];
const before = JSON.stringify(sources);
const result = planSelectedNastils(items, sources, [1, 2]);
assert.equal(result.totalAvailable, 75);
assert.equal(result.plans.length, 1);
assert.deepEqual(result.plans[0].batch_allocations.map(row => [row.production_batch_id, row.quantity]), [[1, 35], [2, 25]]);
assert.deepEqual(result.pendingAllocations.map(row => [row.production_batch_id, row.quantity]), [[2, 15]]);
assert.equal(result.pendingQty, 15);
assert.equal(JSON.stringify(sources), before, "Planning cannot consume the source balances");
for (const selected of [[], [1], [1, 4], [1, 1]]) {
  const plan = planSelectedNastils(items, sources, selected);
  assert.equal(plan.plans.length, 0);
  assert.equal(plan.pendingAllocations.length, 0);
  assert.equal(plan.pendingQty, 0, "A partial pack cannot bypass the two-Nastil selection");
}
assert.equal(planSelectedNastils(items, sources, [1, 2, 3]).totalAvailable, 165);
assert.equal(planSelectedNastils([{ ...items[0], quantity: 1.5 }], sources, [1, 2]).plans.length, 0);
// Bounded varied quantities: every available piece belongs to one exact selected source.
for (let left = 1; left <= 50; left++) for (let right = 1; right <= 50; right++) {
  const plan = planSelectedNastils(items, [{ ...sources[0], available: left }, { ...sources[1], available: right }, sources[2]], [1, 2]);
  const allocations = [...plan.plans.flatMap(row => row.batch_allocations), ...plan.pendingAllocations];
  for (const [id, expected] of [[1, left], [2, right]]) {
    assert.equal(allocations.filter(row => row.production_batch_id === id).reduce((sum, row) => sum + row.quantity, 0), expected);
  }
  assert.ok(allocations.every(row => row.quantity > 0 && row.production_batch_id !== 3));
  assert.equal(plan.plans.length * 60 + plan.pendingQty, left + right);
}
for (const lang of ["en", "ru", "uz"]) assert.equal(typeof library.multiNastilText[lang].chooseTwo, "string");
console.log("PASS: explicit Nastil selection, mixed-source full/partial packs and 2,500 balance integrity scenarios.");
