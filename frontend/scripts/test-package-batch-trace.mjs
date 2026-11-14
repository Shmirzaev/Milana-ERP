import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const compile = file => ts.transpileModule(fs.readFileSync(new URL(file, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
}).outputText;
const library = {};
new Function("exports", compile("../src/lib/packageBatchTrace.ts"))(library);
const { tracePackagePlans, traceCellKey, traceItems, traceItemKey, packageTracePlanKey, traceDraftFromSaved, packageBatchTraceText } = library;
const editor = {};
new Function("exports", "React", "require", compile("../src/components/PackageBatchBreakdownEditor.tsx"))(editor, React, name => {
  assert.equal(name, "@/lib/packageBatchTrace"); return library;
});
const items = [{ model_id: 1, color: "white", size: "M", quantity: 30 }, { model_id: 1, color: "white", size: "L", quantity: 30 }];
const plan = { items, batch_allocations: [{ production_batch_id: 1, quantity: 35, label: "0306-01" }, { production_batch_id: 2, quantity: 25, label: "0306-02" }] };
const draft = {};
for (const [batch, m, l] of [[1, 10, 25], [2, 20, 5]]) {
  draft[traceCellKey(0, batch, items[0])] = String(m);
  draft[traceCellKey(0, batch, items[1])] = String(l);
}
assert.equal(tracePackagePlans([plan], {}).valid, false, "Scalar batch totals cannot prove sizes");
const exact = tracePackagePlans([plan], draft);
assert.equal(exact.valid, true);
assert.deepEqual(traceDraftFromSaved(exact.plans), draft);
for (const [badValue, batch] of [["1.5", 1], ["-1", 1], ["Infinity", 1], ["NaN", 2], ["31", 2]]) {
  assert.equal(tracePackagePlans([plan], { ...draft, [traceCellKey(0, batch, items[0])]: badValue }).valid, false);
}
// Valid row totals with the wrong column totals must still fail.
const wrongColumns = { ...draft, [traceCellKey(0, 1, items[0])]: "15", [traceCellKey(0, 1, items[1])]: "20" };
assert.equal(tracePackagePlans([plan], wrongColumns).valid, false);
const flexiblePlan = { ...plan, batch_allocations: [{ ...plan.batch_allocations[0], quantity: 35 }, { ...plan.batch_allocations[1], quantity: 40 }] };
const flexibleCells = { [traceCellKey(0, 1, items[0])]: "30", [traceCellKey(0, 2, items[1])]: "30" };
const flexible = tracePackagePlans([flexiblePlan], flexibleCells, { 1: 35, 2: 40 });
assert.equal(flexible.valid, true);
assert.deepEqual(flexible.plans[0].batch_allocations.map(row => row.quantity), [30, 30]);
assert.equal(tracePackagePlans([flexiblePlan], flexibleCells, { 1: 35, 2: 40 }, { 1: { M: 35 }, 2: { L: 40 } }).valid, true);
assert.equal(tracePackagePlans([flexiblePlan], draft, { 1: 35, 2: 40 }, { 1: { M: 35 }, 2: { L: 40 } }).valid, false, "Known source sizes cannot be swapped while keeping the package grand total");
assert.equal(tracePackagePlans([flexiblePlan], flexibleCells, { 1: 29, 2: 40 }).valid, false);
const repeated = { ...flexibleCells, [traceCellKey(1, 1, items[0])]: "30", [traceCellKey(1, 2, items[1])]: "30" };
assert.equal(tracePackagePlans([flexiblePlan, flexiblePlan], repeated, { 1: 35, 2: 40 }).valid, false, "Each package may fit independently while their combined source use exceeds inventory");
const fromOneSource = { [traceCellKey(0, 1, items[0])]: "30", [traceCellKey(0, 1, items[1])]: "30" };
const sparse = tracePackagePlans([{ ...flexiblePlan, batch_allocations: flexiblePlan.batch_allocations.map(row => ({ ...row, quantity: 60 })) }], fromOneSource, { 1: 60, 2: 60 });
assert.equal(sparse.valid, true);
assert.equal(sparse.plans[0].batch_allocations.length, 1, "Unused sources must never be sent as zero-quantity allocations");
assert.equal(tracePackagePlans([{ ...plan, batch_allocations: [plan.batch_allocations[0], { ...plan.batch_allocations[1], production_batch_id: 1 }] }], draft).valid, false);
assert.notEqual(packageTracePlanKey([plan]), packageTracePlanKey([{ ...plan, items: items.map(item => ({ ...item, size: "XL" })) }]));
assert.notEqual(packageTracePlanKey([plan]), packageTracePlanKey([{ ...plan, batch_allocations: [...plan.batch_allocations].reverse() }]));
assert.equal(tracePackagePlans([{ items, batch_allocations: [{ ...plan.batch_allocations[0], quantity: 60 }] }], {}).valid, true);
assert.equal(tracePackagePlans([{ ...plan, items: [{ ...items[0], quantity: 60 }] }], {}).valid, true, "One identity is uniquely attributable without guessed proportions");
assert.notEqual(traceItemKey(items[0]), traceItemKey({ ...items[0], model_id: 2 }));
assert.notEqual(traceItemKey(items[0]), traceItemKey({ ...items[0], color: "blue" }));
assert.equal(traceItems([items[0], { ...items[0], color: " WHITE ", quantity: 5 }])[0].quantity, 35);

for (const lang of ["en", "ru", "uz"]) {
  const html = renderToStaticMarkup(React.createElement(editor.default, { plans: [plan], draft, onChange() {}, lang }));
  assert.ok(html.includes(packageBatchTraceText[lang].title));
  assert.ok(html.includes("0306-01") && html.includes("0306-02"));
  assert.match(html, /10 \/ 30|30 \/ 30/);
  assert.ok(!html.includes(packageBatchTraceText[lang].invalid));
  const incomplete = renderToStaticMarkup(React.createElement(editor.default, { plans: [plan], draft: {}, onChange() {}, lang }));
  assert.ok(incomplete.includes(packageBatchTraceText[lang].invalid));
}
// Deterministic bounded conservation cases with 2 identities and 2 sources.
for (let a = 0; a <= 20; a++) for (let b = 0; b <= 20; b++) {
  if (!a && !b) continue;
  const rows = [{ ...items[0], quantity: a + 3 }, { ...items[1], quantity: b + 7 }];
  const candidate = { items: rows, batch_allocations: [{ ...plan.batch_allocations[0], quantity: a + b }, { ...plan.batch_allocations[1], quantity: 10 }] };
  const values = {};
  for (const [batch, m, l] of [[1, a, b], [2, 3, 7]]) {
    values[traceCellKey(0, batch, rows[0])] = String(m); values[traceCellKey(0, batch, rows[1])] = String(l);
  }
  const before = JSON.stringify(candidate);
  const result = tracePackagePlans([candidate], values);
  assert.equal(result.valid, true);
  assert.equal(JSON.stringify(candidate), before, "Planning cannot mutate source evidence");
  assert.ok(result.plans[0].batch_allocations.every(row => row.item_breakdown.every(item => item.quantity > 0)));
}
console.log("PASS: exact batch/model/color/size conservation, unknown and stale drafts, 440 varied allocations and EN/RU/UZ editor renders.");
