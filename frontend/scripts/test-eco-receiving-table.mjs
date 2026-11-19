import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
import React from "react";
import * as jsx from "react/jsx-runtime";
import {renderToStaticMarkup} from "react-dom/server";

const read = path => fs.readFileSync(new URL(path, import.meta.url), "utf8");
function compile(source, deps = {}) {
  const output = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX}}).outputText;
  const exports = {};
  new Function("exports", "require", output)(exports, name => {assert.ok(name in deps, name); return deps[name];});
  return exports;
}
function walk(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(walk);
  if (typeof node.type === "function") return walk(node.type(node.props));
  return [node, ...walk(node.props?.children)];
}
const qc = compile(read("../src/lib/inventoryQcStatus.ts"));
const lib = compile(read("../src/lib/ecoReceiptTable.ts"), {"./inventoryQcStatus": qc});
const stock = compile(read("../src/lib/ecoInventory.ts"));
const receipt = compile(read("../src/lib/ecoReceipt.ts"), {"./inventoryQcStatus": qc});
const base = lib.newEcoReceiptRow("fabric");
const measured = lib.ecoReceiptRowBody({...base, item_id: 1, batch_no: " A ", mode: "rolls", weights: ["0.1", "0.2"], lengths: ["", "12.5"], details: {gsm: "220", image_url: "/exact-batch.webp"}}, "fabric");
assert.equal(measured.quantity, "0.3000");
assert.deepEqual(measured.roll_lengths_m, [null, "12.5"]);
assert.equal(measured.piece_count, 2);
assert.equal(measured.batch_no, "A");
assert.equal(measured.gsm, "220");
assert.equal(measured.image_url, "/exact-batch.webp");
assert.equal(lib.ecoReceiptRowBody({...base, mode: "length", quantity: "5.125", unit: "m"}, "fabric").length_m, "5.125");
assert.equal(lib.newEcoReceiptRow("accessory").unit, "pcs");

const items = [{id: 1, name: "Cotton", sku: "FAB", unit: "kg", category: "fabric"}, {id: 2, name: "Buttons", sku: "BTN", unit: "pcs", category: "accessory"}, {id: 3, name: "Carton", sku: "BOX", unit: "pcs", category: "packaging"}];
globalThis.requestAnimationFrame = callback => callback();
for (const lang of ["en", "ru", "uz"]) for (const kind of ["accessory", "fabric"]) {
  const states = []; let cursor = 0; const sent = [];
  const react = {...React, useState(initial) {const id = cursor++; if (!(id in states)) states[id] = typeof initial === "function" ? initial() : initial;
    return [states[id], value => {states[id] = typeof value === "function" ? value(states[id]) : value;}];}, useId: () => "initial-row", useRef: () => ({current: null})};
  const Form = compile(read("../src/components/inventory/EcoReceiptForm.tsx"), {
    react, "react/jsx-runtime": jsx, "next/link": {default: props => React.createElement("a", props)},
    "lucide-react": {Plus: () => null, Trash2: () => null},
    swr: {default: url => ({data: url.includes("/items?") ? items : url.endsWith("suppliers") ? [{id: 7, name: "Supplier"}] : url.endsWith("warehouses") ? [{id: 8, name: "ECO warehouse"}] : [], mutate: async () => {}})},
    "@/components/SearchableSelect": {default: props => React.createElement("select", {value: props.value ?? "", onChange: props.onChange, "data-picker": props.inputId}, props.options.map(row => React.createElement("option", {key: row.value, value: row.value}, row.label)))},
    "@/components/MaterialRollWeightFields": {default: () => null},
    "@/lib/api": {api: {}, fetcher() {}}, "@/lib/i18n": {useT: () => ({lang, t: key => key})},
    "@/lib/auth": {can: () => true, useMe: () => ({me: {}})}, "@/lib/inventoryQcStatus": qc,
    "@/lib/ecoInventory": stock, "@/lib/ecoReceipt": receipt, "@/lib/ecoReceiptTable": lib,
  }).default;
  function render() {cursor = 0; return Form({kind, busy: false, onSubmit: body => sent.push(body), onCancel() {}});}
  const nodes = () => walk(render());
  const html = renderToStaticMarkup(render());
  assert.ok(html.includes("<table"));
  for (const token of [lib.ecoReceiptTableText(lang).type, lib.ecoReceiptTableText(lang).name]) assert.ok(html.includes(token));
  const byAria = label => nodes().find(node => node.props?.["aria-label"] === label);
  const text = stock.ecoInventoryText(lang);
  byAria(`${text.quantity} · 1`).props.onChange({target: {value: "12"}});
  byAria(`${text.batch} · 1`).props.onChange({target: {value: "LOT-A"}});
  nodes().find(node => node.props?.["data-picker"]?.startsWith("eco-item-")).props.onChange(kind === "fabric" ? 1 : 2);
  let prevented = false;
  byAria(`${text.batch} · 1`).props.onKeyDown({key: "Enter", preventDefault() {prevented = true;}});
  assert.ok(prevented); assert.equal(sent.length, 0);
  assert.equal(nodes().filter(node => node.type === "tr" && node.props["data-row-key"]).length, 2);
  byAria(`${text.quantity} · 2`).props.onChange({target: {value: "3"}});
  byAria(`${text.batch} · 2`).props.onChange({target: {value: "LOT-B"}});
  nodes().filter(node => node.props?.["data-picker"]?.startsWith("eco-item-"))[1].props.onChange(kind === "fabric" ? 1 : 2);
  nodes().find(node => node.props?.id === "eco-receipt-warehouse").props.onChange({target: {value: "8"}});
  render().props.onSubmit({preventDefault() {}});
  assert.equal(sent.length, 1);
  assert.deepEqual(sent[0].lines.map(row => row.batch_no), ["LOT-A", "LOT-B"]);
  assert.deepEqual(sent[0].lines.map(row => row.quantity), ["12", "3"]);
  assert.ok(sent[0].lines.every(row => row.warehouse_id === 8));
  assert.ok(sent[0].request_key);
  assert.equal(sent[0].lines[0].received_date, sent[0].lines[1].received_date);
  byAria(`${lib.ecoReceiptTableText(lang).remove} · 2`).props.onClick();
  assert.equal(nodes().filter(node => node.type === "tr" && node.props["data-row-key"]).length, 1);
}
console.log("ECO receipt table: EN/RU/UZ rendering, Enter adds, separate lots, shared header, save/remove and exact decimal roll totals passed.");
