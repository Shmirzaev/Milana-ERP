import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";

const source = fs.readFileSync("src/lib/fabricSource.ts", "utf8");
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS } }).outputText;
const exports = {};
new Function("exports", code)(exports);
const rows = exports.fabricSelectionRows([{ id: 7, batch_no: "MIL source", eco_material_batch_id: null },
  { id: null, batch_no: "ECO direct", eco_material_batch_id: 7 }]);
assert.deepEqual(rows.map(row => row.id), [7, -7], "Equal numeric IDs from separate ledgers must remain distinct selections");
assert.deepEqual(exports.fabricSourceInput(rows[0].id), { stock_batch_id: 7, eco_material_batch_id: null });
assert.deepEqual(exports.fabricSourceInput(rows[1].id), { stock_batch_id: null, eco_material_batch_id: 7 });
assert.deepEqual(exports.primaryFabricSourceInput(rows[1].id), { fabric_batch_id: null, eco_fabric_batch_id: 7 });
for (const row of rows) {
  const input = exports.fabricSourceInput(row.id);
  assert.ok(Object.values(input).filter(value => value !== null).every(value => value > 0), "Local keys cannot enter foreign-key inputs");
}
console.log("ECO fabric selections keep separate source identities and send only explicit positive API IDs.");

// Exercise the actual Cutting option calculations. An available ECO identity
// must survive a zero Milana balance; a held/missing ECO balance cannot fall
// back to the same ID's positive Milana remainder.
const page = fs.readFileSync("src/app/(app)/work-orders/[id]/cutting/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", page, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const helpers = new Set(["uniqueBatchOptions", "reservationForOrder", "batchAvailableQty"]);
const parts = [];
function visit(node) {
  if (ts.isFunctionDeclaration(node) && helpers.has(node.name?.text)) parts.push(node.getText(ast));
  if (ts.isVariableDeclaration(node) && ["fabricBatches", "allSearchableFabricBatches"].includes(node.name.getText(ast))) parts.push(`const ${node.getText(ast)};`);
  ts.forEachChild(node, visit);
}
visit(ast);
const calculations = ts.transpileModule(`${parts.join("\n")} return allSearchableFabricBatches;`, {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText;
const calculate = new Function("useMemo", "materialItemIds", "po", "MATERIAL_BATCH_CATEGORIES", "batches", "allMaterialBatches", "ecoMaterialBatches", "isEcoCottonCutting", calculations);
const central = [{ id: 1, item_id: 4, item_category: "fabric", quantity: 0, available_quantity: 0 },
  { id: 2, item_id: 4, item_category: "fabric", quantity: 1000, available_quantity: 1000 }];
const eco = [{ ...central[0], quantity: 100, reserved_quantity: 10, available_quantity: 90, unit: "kg" },
  { id: 3, item_id: 5, item_category: "fabric", quantity: 12, available_quantity: 12 }];
const result = calculate(fn => fn(), [], { id: 10 }, new Set(["fabric", "semi_finished"]), central, central, eco, true);
assert.deepEqual(result.map(row => row.id).sort(), [1, 3]);
assert.equal(result.find(row => row.id === 1).available_quantity, 90);
assert.equal(result.find(row => row.id === 1).reserved_quantity, 10);
assert.equal(result.some(row => row.id === 2), false);
const milana = calculate(fn => fn(), [], { id: 10 }, new Set(["fabric", "semi_finished"]), central, central, eco, false);
assert.deepEqual(milana.map(row => row.id), [2]);
console.log("Actual Cutting option calculations use authoritative ECO availability and preserve central-factory choices.");

const statistics = [];
function findStatistics(node) {
  if (ts.isJsxElement(node)) {
    const text = node.getText(ast);
    if (text.includes('t("field.reserved")') && text.includes('t("page.cutting.onHand")')) statistics.push(text);
  }
  ts.forEachChild(node, findStatistics);
}
findStatistics(ast);
const fragment = statistics.sort((a, b) => a.length - b.length)[0];
assert.ok(fragment, "Render the actual Cutting batch statistics");
const compiled = ts.transpileModule(`exports.element = (${fragment});`, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const rendered = {};
const t = key => ({ "field.available": "Available", "page.cutting.onHand": "On hand", "field.reserved": "Reserved" }[key] || key);
new Function("exports", "require", "selectedFabricBatch", "selectedFabricReservation", "t", "fmtQty", "batchAvailableQty", compiled)(
  rendered, name => { assert.equal(name, "react/jsx-runtime"); return jsxRuntime; }, result.find(row => row.id === 1), null,
  t, value => Number(value || 0).toString(), row => row.available_quantity,
);
const html = renderToStaticMarkup(React.createElement(() => rendered.element));
assert.match(html, /Available:.*90.*kg/);
assert.match(html, /On hand:.*100.*kg/);
assert.match(html, /Reserved:.*10.*kg/);
assert.ok(!html.includes("forThisOrder"), "Batch reserved total is separate from a per-order allocation");
console.log("Actual Cutting statistics render authoritative available90/on-hand100/reserved10 independently of order allocation.");
