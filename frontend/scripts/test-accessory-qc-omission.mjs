import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const receive = read("../src/app/(app)/inventory/receive/page.tsx");
const inventory = read("../src/app/(app)/inventory/page.tsx");
const parse = (source) => ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function find(tree, predicate) {
  if (predicate(tree)) return tree;
  return ts.forEachChild(tree, (child) => find(child, predicate));
}
function fn(source, name) {
  const node = find(parse(source), (node) => ts.isFunctionDeclaration(node) && node.name?.text === name);
  assert.ok(node, `Missing actual function ${name}`);
  return node.getText();
}
function compile(source, dependencies = {}) {
  const context = { ...dependencies, exports: {}, require: (name) => {
    assert.equal(name, "react/jsx-runtime");
    return jsx;
  } };
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, context);
  return context.exports;
}
const { InventoryQcStatus, INVENTORY_QC_STATUSES } = compile(read("../src/lib/inventoryQcStatus.ts"));
const helpers = compile([
  fn(receive, "numberOrZero"), fn(receive, "isMeterUnit"), fn(receive, "toReceivePayload"),
  fn(receive, "toAccessoryReturnPayload"), fn(inventory, "optionalNumber"), fn(inventory, "batchPayload"),
  "export { toReceivePayload, toAccessoryReturnPayload, batchPayload };",
].join("\n"), {
  ...compile(read("../src/lib/materialRollWeights.ts")),
});
const form = {
  item_id: 7, production_order_id: 21, batch_no: "1001", supplier_id: 0,
  color: "", old_code: "ELA:1:7", color_code: "", color_status: "", order_no: "",
  width: "", gsm: "", quantity: 258, piece_count: "", processes: "Opening stock",
  unit: "kg", cost_per_unit: 0, image_url: "", received_date: "", warehouse_id: 2,
  roll_weights_kg: [], roll_lengths_m: [], weight_entry: "total", return_condition: "used",
};
for (const status of INVENTORY_QC_STATUSES) {
  const input = { ...form, qc_status: status };
  const before = JSON.stringify(input);
  for (const payload of [helpers.toReceivePayload(input, false), helpers.toAccessoryReturnPayload(input), helpers.batchPayload(input, "accessories")]) {
    assert.ok(!Object.hasOwn(payload, "qc_status"), `Accessories must omit QC even when form contains ${status}`);
    assert.equal(payload.quantity, 258);
    assert.equal(payload.old_code, "ELA:1:7");
  }
  assert.equal(helpers.toReceivePayload(input, true).qc_status, status);
  assert.equal(helpers.batchPayload(input, "materials").qc_status, status);
  assert.equal(helpers.toAccessoryReturnPayload(input).production_order_id, 21);
  assert.equal(JSON.stringify(input), before, "Building a payload must not rewrite the stored QC state");
}

// Render the real receiving form, including the accessory return configuration.
const { StockForm } = compile(`${fn(receive, "isMeterUnit")}\n${fn(receive, "StockForm")}\nexport { StockForm };`, {
  useState: React.useState, useT: () => ({ t: (key) => key }),
  MATERIAL_COLOR_OPTIONS: [], InventoryQcStatus,
  RECEIPT_QC_STATUSES: [InventoryQcStatus.PENDING, InventoryQcStatus.PASSED, InventoryQcStatus.FAILED],
});
const props = { title: "Receive", itemLabel: "Item", submitLabel: "Save", form: { ...form, qc_status: "passed" },
  customColors: [], message: "", onChange() {}, onAddColor() {}, onSubmit() {} };
for (const extra of [{}, { showReturnCondition: true, requireOrder: true }]) {
  const html = renderToStaticMarkup(React.createElement(StockForm, { ...props, ...extra }));
  assert.ok(!html.includes("page.receiveStock.qcStatus"));
  assert.ok(!html.includes('value="passed"'));
}
const fabric = renderToStaticMarkup(React.createElement(StockForm, { ...props, showFabricDetails: true }));
assert.ok(fabric.includes("page.receiveStock.qcStatus") && fabric.includes('value="passed"'));

// Exercise the exact QC edit wrapper and table header JSX from the inventory page.
const tree = parse(inventory);
const edit = find(tree, (node) => ts.isJsxExpression(node) && node.getText().startsWith('{group === "materials" && <div>') && node.getText().includes('t("page.receiveStock.qcStatus")'));
const header = find(tree, (node) => ts.isJsxElement(node) && node.openingElement.tagName.getText() === "th" && node.getText().includes('t("page.receiveStock.qcStatus")'));
assert.ok(edit && header, "QC editor and column header must remain scoped to materials");
const { renderInventory } = compile(`export function renderInventory(group) { return <>${edit.getText()}${header.getText()}</>; }`, {
  t: (key) => key, batchForm: { qc_status: "passed" }, INVENTORY_QC_STATUSES, qcLabel: (status) => status,
});
assert.ok(!renderToStaticMarkup(renderInventory("accessories")).includes("page.receiveStock.qcStatus"));
assert.ok(renderToStaticMarkup(renderInventory("materials")).includes("page.receiveStock.qcStatus"));
for (const group of ["accessories", "materials"]) {
  const { batchReceiveDetails } = compile(`${fn(inventory, "batchReceiveDetails")}\nexport { batchReceiveDetails };`, {
    group, t: (key) => key, qcLabel: (status) => status, fmtDecimal: String,
    receivedDateLabel: String, textOrDash: (value) => value == null || value === "" ? "-" : String(value),
  });
  const details = batchReceiveDetails({ ...form, qc_status: "pending" });
  assert.equal(details.some((detail) => detail.label === "page.receiveStock.qcStatus"), group === "materials");
  assert.ok(details.some((detail) => detail.value === "Opening stock"));
}
assert.match(receive, /toReceivePayload\(receiveForm, isFabricReceiving\)/);
assert.match(receive, /showFabricDetails=\{isFabricReceiving\}/);
assert.match(inventory, /batchPayload\(batchForm, group\)/);
console.log("Accessory receipt/return/edit payload omission and rendered QC visibility pass; material QC remains intact.");
