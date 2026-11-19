import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsx from "react/jsx-runtime";

const read = path => fs.readFileSync(new URL(path, import.meta.url), "utf8");
function compile(source, dependencies = {}) {
  const output = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("exports", "require", output)(exports, name => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  });
  return exports;
}

// Execute the actual size-change function: no manufactured pieces on model selection,
// and no inflation when an explicitly entered total is smaller than the size count.
const planning = read("../src/app/(app)/planning/page.tsx");
const tree = ts.createSourceFile("planning.tsx", planning, ts.ScriptTarget.Latest, true);
const distribute = tree.statements.find(node => ts.isFunctionDeclaration(node)
  && node.name?.text === "distributeExistingQuantityAcrossSizes");
const { distributeExistingQuantityAcrossSizes } = compile(`const numberOrZero = v => Number(v || 0); export ${distribute.getText(tree)}`);
assert.deepEqual(distributeExistingQuantityAcrossSizes(["S", "M", "L"], [{ quantity: "", color: "white" }])
  .map(row => row.quantity), ["", "", ""]);
assert.deepEqual(distributeExistingQuantityAcrossSizes(["S", "M", "L"], [{ quantity: 2, color: "white" }])
  .map(row => row.quantity), [1, 1, 0]);
assert.deepEqual(distributeExistingQuantityAcrossSizes(["S", "M", "L"], [{ quantity: 11, color: "white", printing_required: true }])
  .map(row => row.quantity), [4, 4, 3]);
const defaults = [...planning.matchAll(/lines: \[\{ color: "white", size: "", quantity: ([^,]+), printing_required: false \}\]/g)];
assert.equal(defaults.length, 2);
assert.deepEqual(defaults.map(match => match[1]), ['""', '""']);

const variant = compile(read("../src/lib/variantDisplay.ts"));
const reviewText = compile(read("../src/lib/shipmentReviewText.ts"));
const warehouseText = compile(read("../src/lib/warehousePackageText.ts"));
for (const lang of ["en", "ru", "uz"]) {
  const { default: Panel } = compile(read("../src/components/ShipmentReviewPanel.tsx"), {
    react: React, "react/jsx-runtime": jsx,
    "@/lib/api": { api: {} }, "@/lib/variantDisplay": variant,
    "@/lib/auth": { useMe: () => ({ me: {} }), can: () => true },
    "@/lib/i18n": { useT: () => ({ lang, t: key => key }) },
    "@/lib/shipmentReviewText": reviewText, "@/lib/warehousePackageText": warehouseText,
  });
  const html = renderToStaticMarkup(React.createElement(Panel, {
    preparation: { shipment: { id: 1, status: "created" },
      review: { quantity: 90, packages_count: 2, amount: null },
      packages: [{ id: 1, package_no: "PKG-A", model_no: "A100", variant_no: "02", quantity: 60, scanned: true },
        { id: 2, package_no: "PKG-B", model_code: "B200", variant_no: "V-03", quantity: 30, scanned: true },
        { id: 3, package_no: "PKG-HIDDEN", model_no: "UNSCANNED", quantity: 10, scanned: false }] },
    onChanged: async () => {},
  }));
  for (const value of ["PKG-A", "A100", "V-02", "PKG-B", "B200", "V-03"]) assert.ok(html.includes(value), `${lang}: ${value}`);
  assert.ok(!html.includes("V-V-03"));
  assert.ok(!html.includes("UNSCANNED"));
}
console.log("Planning blank quantities, exact total distribution and per-package model/variant rendering passed (EN/RU/UZ).");

function walk(node) {
  if (!node || typeof node !== "object") return [];
  if (Array.isArray(node)) return node.flatMap(walk);
  if (typeof node.type === "function") return walk(node.type(node.props));
  return [node, ...walk(node.props?.children)];
}
const rejectionText = compile(read("../src/lib/cuttingRejectionText.ts"));
for (const lang of ["en", "ru", "uz"]) {
  const state = [];
  let cursor = 0, permitted = true, failWrite = true, requests = 0;
  const { default: Reject } = compile(read("../src/components/CuttingRejectOrder.tsx"), {
    react: { useId: () => "qa-reason", useState: initial => {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], value => { state[index] = value; }];
    } }, "react/jsx-runtime": jsx,
    "@/components/Modal": { default: props => props.open ? props.children : null },
    "@/lib/api": { api: { post: async (path, payload) => {
      requests++; assert.equal(path, "/api/work-orders/19/reject-cutting");
      assert.deepEqual(payload, { reason: "No fabric" });
      if (failWrite) throw new Error("409: Already recorded output");
    } } },
    "@/lib/auth": { useMe: () => ({ me: {} }), can: () => permitted },
    "@/lib/i18n": { useT: () => ({ lang }) }, "@/lib/cuttingRejectionText": rejectionText,
  });
  const props = { workOrderId: 19, status: "in_progress", hasOutput: false,
    orderLabel: "PO-QA", onRejected: async () => { throw new Error("Refresh failed after saved rejection"); } };
  const render = overrides => { cursor = 0; return walk(Reject({ ...props, ...overrides })); };
  permitted = false; assert.equal(render().length, 0); permitted = true;
  for (const status of ["rejected", "cancelled", "completed"]) assert.equal(render({ status }).length, 0);
  assert.equal(render({ hasOutput: true }).length, 0);
  render().find(node => node.type === "button").props.onClick();
  let nodes = render();
  assert.equal(nodes.find(node => node.type === "button" && node.props.type === "submit").props.disabled, true);
  nodes.find(node => node.type === "textarea").props.onChange({ target: { value: "  " } });
  await render().find(node => node.type === "form").props.onSubmit({ preventDefault() {} });
  assert.equal(requests, 0);
  nodes = render(); assert.ok(nodes.some(node => node.props.role === "alert"));
  nodes.find(node => node.type === "textarea").props.onChange({ target: { value: "  No fabric  " } });
  await render().find(node => node.type === "form").props.onSubmit({ preventDefault() {} });
  nodes = render(); assert.equal(nodes.find(node => node.type === "textarea").props.value, "  No fabric  ");
  assert.ok(nodes.some(node => node.props.role === "alert"));
  failWrite = false;
  await nodes.find(node => node.type === "form").props.onSubmit({ preventDefault() {} });
  nodes = render(); assert.equal(requests, 2);
  assert.ok(nodes.some(node => node.props.role === "status" && node.props.children === rejectionText.cuttingRejectionText[lang].saved));
  assert.ok(nodes.some(node => node.props.role === "alert" && node.props.children.includes("Refresh failed")));
  assert.ok(!nodes.some(node => node.type === "button"));
}
console.log("Cutting rejection permission/terminal/output visibility, blank refusal, retained failed draft and saved-refresh-failure passed (EN/RU/UZ).");
