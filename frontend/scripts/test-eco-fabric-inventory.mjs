import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";

const read = path => fs.readFileSync(new URL(path, import.meta.url), "utf8");
function compile(source, dependencies = {}) {
  const output = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  const exports = {};
  new Function("exports", "require", output)(exports, name => {
    assert.ok(name in dependencies, `Unexpected dependency: ${name}`);
    return dependencies[name];
  });
  return exports;
}
function walk(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(walk);
  if (typeof node.type === "function") return walk(node.type(node.props));
  return [node, ...walk(node.props?.children)];
}
const eco = compile(read("../src/lib/ecoInventory.ts"));
const qc = compile(read("../src/lib/inventoryQcStatus.ts"));
const receipt = compile(read("../src/lib/ecoReceipt.ts"), {"./inventoryQcStatus": qc});
const rows = [
  {id: 11, item_id: 2, sku: "FAB-A", item_name: "Cotton", batch_no: "EXACT-A", kind: "fabric", color: "Red", unit: "kg",
    quantity: "436.1250", reserved_quantity: "36.1250", available_quantity: "400.0000",
    receipt_details: {image_url: "/batch-a.webp", qc_status: "passed", cost_per_unit: "2.5", supplier_name: "QA supplier",
      warehouse_name: "ECO store", width: "180", gsm: "220", old_code: "OLD-A", color_code: "C09", document_no: "DOC-A"}},
  {id: 12, item_id: 2, sku: "FAB-A", item_name: "Cotton", batch_no: "EXACT-B", kind: "fabric", color: "Blue", unit: "kg",
    quantity: "5", reserved_quantity: "5", available_quantity: "0", receipt_details: {image_url: "/batch-b.webp", qc_status: "hold"}},
];
for (const lang of ["en", "ru", "uz"]) {
  const i18n = {useT: () => ({lang, t: key => key})};
  const details = compile(read("../src/components/inventory/EcoReceiptDetails.tsx"), {
    "react/jsx-runtime": jsx, "@/lib/i18n": i18n, "@/lib/ecoReceipt": receipt,
  });
  const {default: Stock} = compile(read("../src/components/inventory/EcoFabricStock.tsx"), {
    "react/jsx-runtime": jsx, "@/lib/i18n": i18n, "@/lib/ecoInventory": eco, "@/lib/ecoReceipt": receipt,
    "@/lib/inventoryQcStatus": qc, "@/components/inventory/EcoReceiptDetails": details,
    "@/components/ImageThumbnail": {default: props => React.createElement("img", {src: props.imageUrl, alt: props.label})},
  });
  const changes = [], consumed = [];
  const props = {rows, busy: false, uncertain: false, canUpdateQuality: true, canConsume: true,
    onQuality: (row, value) => changes.push([row.id, value]), onConsume: row => consumed.push(row.id)};
  const tree = Stock(props);
  const html = renderToStaticMarkup(tree);
  for (const token of ["EXACT-A", "EXACT-B", "OLD-A", "C09", "180", "220", "QA supplier", "ECO store", "DOC-A", "1320px", "md:hidden"])
    assert.ok(html.includes(token), `${lang}: missing ${token}`);
  assert.equal((html.match(/src="\/batch-a.webp" alt="Cotton · EXACT-A"/g) || []).length, 2);
  assert.equal((html.match(/src="\/batch-b.webp" alt="Cotton · EXACT-B"/g) || []).length, 2);
  const nodes = walk(tree);
  const selects = nodes.filter(node => node.type === "select");
  assert.equal(selects.length, 4);
  selects[0].props.onChange({target: {value: "hold"}});
  assert.deepEqual(changes, [[11, "hold"]]);
  const buttons = nodes.filter(node => node.type === "button");
  assert.equal(buttons[0].props.disabled, false);
  assert.equal(buttons[1].props.disabled, true);
  buttons[0].props.onClick(); assert.deepEqual(consumed, [11]);
  assert.ok(walk(Stock({...props, uncertain: true})).filter(node => node.type === "button").every(node => node.props.disabled));
  assert.ok(walk(Stock({...props, busy: true})).filter(node => node.type === "button" || node.type === "select").every(node => node.props.disabled));
  const readonly = renderToStaticMarkup(Stock({...props, canUpdateQuality: false, canConsume: false}));
  assert.ok(!readonly.includes("<select") && !readonly.includes("<button"));
  assert.ok(renderToStaticMarkup(Stock({...props, rows: []})).includes(eco.ecoInventoryText(lang).empty));
}
const page = read("../src/app/(app)/eco-inventory/page.tsx");
assert.ok(page.includes('view === "stock" && kind === "fabric" ? <EcoFabricStock'));
assert.ok(page.includes('/api/eco-inventory/stock?kind=${kind}&limit=${pageSize}&offset=${page * pageSize}&q='));
assert.ok(!page.includes('"/api/inventory/stock'));
console.log("ECO fabric Milana-style table/mobile rendering, exact-batch photos, metadata, permissions and stock action boundaries passed (EN/RU/UZ).");
