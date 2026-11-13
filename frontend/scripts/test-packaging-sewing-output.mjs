import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/work-orders/[id]/packaging/page.tsx", import.meta.url), "utf8");
const multiNastil = {};
new Function("exports", ts.transpileModule(fs.readFileSync(new URL("../src/lib/multiNastilPackaging.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(multiNastil);
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React,
} }).outputText;

function render(sewn, remaining, batched = true, events = {}) {
  let stateIndex = 0;
  const batch = { id: 1, name: "Nastil 1", batch_no: "0306-01", planned_quantity: 684,
    sewing_output_qty: sewn, available_input_qty: remaining, packed_qty: 0, available_to_package: 0 };
  const noop = () => null;
  const deps = {
    react: { ...React, useState: initial => {
      const index = stateIndex++;
      return React.useState(events.states?.[index] ?? (index === 0
        ? { ...initial, production_batch_id: batched ? 1 : 0 } : initial));
    } },
    "next/navigation": { useParams: () => ({ id: "3" }) },
    swr: { useSWRConfig: () => ({ mutate: async predicate => { events.sizePredicate = predicate; } }),
      default: key => ({ mutate: async () => { (events.refreshed ??= []).push(key); }, data:
      key?.startsWith("/api/packages/sources/") ? { items: events.sources || events.batches || [batch] }
      : key?.includes("packaging-batch-progress") ? { ...batch, items: batched ? (events.batches || [batch]) : [] }
      : key?.includes("production-orders") ? { id: 1, model_id: 1, planned_quantity: 684,
        batches: batched ? [batch] : [], items: [{ size: "M", color: "white", planned_quantity: 684 }] }
      : key?.includes("work-orders") ? { id: 3, production_order_id: 1, planned_output_qty: 684, passed_qty: 0 }
      : key === "/api/customers" ? [] : undefined }) },
    "@/lib/api": { api: { openLabel: async () => {} }, fetcher: noop },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: {} }) },
    "@/lib/i18n": { useT: () => ({ t: (key, vars) => {
      if (events.translations) events.translations[key] = vars;
      return key;
    }, lang: "en" }) },
    "@/lib/multiNastilPackaging": multiNastil,
    "@/lib/errorMessages": { localizeError: value => value },
    "@/lib/batchSerial": { formatBatchLabel: row => row.name, formatBatchSerial: row => row.batch_no },
    "@/lib/packageWorkflow": { postPackageWorkflow: async (_path, body) => { events.created = body; return { id: 1, count: body.packages.length, package_ids: [1], run_no: "PRN-1" }; } },
    "@/lib/orderRef": { orderReference: () => "PO-0306" },
    "@/lib/numberInput": { numberOrZero: value => Number(value || 0), numberOrFallback: (v, f) => Number(v || f), parseNumberInput: Number },
    "@/components/StagePipeline": { operationLabel: value => value, statusLabel: value => value },
    "@/components/PackageQrSection": { default: props => { events.packageChanged = props.onChanged; return null; } },
  };
  const exports = {};
  const react = { ...React, createElement: (type, props, ...children) => {
    if (type === "form" && props.onSubmit) events.submitPackage = props.onSubmit;
    return React.createElement(type, props, ...children);
  } };
  new Function("exports", "React", "require", compiled)(exports, react, name => {
    if (name in deps) return deps[name];
    assert.ok(name.startsWith("@/components/"), `Unexpected dependency ${name}`);
    return { default: noop };
  });
  return renderToStaticMarkup(React.createElement(exports.default));
}

for (const [sewn, remaining] of [[590, 590], [585, 285], [0, 0]]) {
  const html = render(sewn, remaining);
  assert.ok(html.includes(`Nastil 1 (${sewn})`));
  assert.ok(!html.includes("Nastil 1 (684)"));
  assert.match(html, new RegExp(`min="0" max="${remaining}" value=""`));
  assert.ok(html.includes(`field.available: ${remaining}`));
}
assert.match(render(585, 285, false), /min="0" max="285" value=""/);

// Exercise the actual page submit closure, not just the planner: source selection
// must reach the atomic endpoint and must not create packs from the third Nastil.
const merged = { states: { 7: 2, 9: true, 10: [1, 2] }, batches: [], sources: [
  { id: 1, name: "Nastil A", available_to_package: 35 },
  { id: 2, name: "Nastil B", available_to_package: 40 },
  { id: 3, name: "Unselected", available_to_package: 90 },
  { id: 4, name: "Still sewing", available_to_package: 0 },
] };
const mergedHtml = render(75, 0, true, merged);
assert.match(mergedHtml, /Selected Nastils: 2/);
assert.match(mergedHtml, /aria-label="Select Still sewing" disabled=""/);
await merged.submitPackage({ preventDefault() {} });
assert.equal(merged.created.packages.length, 2);
assert.deepEqual(merged.created.packages.map(pack => pack.items.reduce((sum, item) => sum + item.quantity, 0)), [60, 15]);
assert.deepEqual(merged.created.packages.flatMap(pack => pack.batch_allocations.map(row => [row.production_batch_id, row.quantity])), [[1, 35], [2, 25], [2, 15]]);
const onePack = { ...merged, states: { 7: 1, 9: true, 10: [1, 2] }, created: undefined };
render(75, 0, true, onePack);
await onePack.submitPackage({ preventDefault() {} });
assert.equal(onePack.created.packages.length, 1);
assert.deepEqual(onePack.created.packages[0].batch_allocations.map(row => [row.production_batch_id, row.quantity]), [[1, 35], [2, 25]]);
// The real single-source submit must stop after the requested full or partial pack.
for (const [quantity, copies, expected] of [[300, 1, [60]], [130, 2, [60, 60]], [75, 2, [60, 15]], [75, 5, [60, 15]], [0, 1, []]]) {
  const events = { states: { 7: copies }, batches: [{ id: 1, packed_qty: quantity, available_to_package: quantity }] };
  render(quantity, 0, true, events);
  await events.submitPackage({ preventDefault() {} });
  assert.deepEqual((events.created?.packages || []).map(pack => pack.items.reduce((sum, item) => sum + item.quantity, 0)), expected);
}
// Source previews must describe the selected final plans, including a pure
// first pack before a mixed second pack and the final partial pack.
for (const [copies, balances, expected, preview, fullCount, pending] of [
  [1, [90, 90], [[[1, 60]]], "Nastil A: 60", 1, 120],
  [2, [90, 90], [[[1, 60]], [[1, 30], [2, 30]]], "Nastil A: 60 | Nastil A: 30 + Nastil B: 30", 2, 60],
  [2, [35, 40], [[[1, 35], [2, 25]], [[2, 15]]], "Nastil A: 35 + Nastil B: 25 | Nastil B: 15", 1, 0],
]) {
  const events = { states: { 7: copies, 9: true, 10: [1, 2] }, translations: {}, sources: [
    { id: 1, name: "Nastil A", available_to_package: balances[0] },
    { id: 2, name: "Nastil B", available_to_package: balances[1] },
    { id: 3, name: "Unselected", available_to_package: 90 },
  ] };
  const html = render(balances[0] + balances[1], 0, true, events);
  assert.ok(html.includes(`page.packaging.mergeSources: ${preview}`), preview);
  if (copies === 1) assert.ok(!html.includes("Nastil A: 30 + Nastil B: 30"), "Never preview an unselected second pack");
  assert.equal(events.translations["page.packaging.mergeFullPackages"].count, fullCount);
  assert.equal(events.translations["page.packaging.mergePending"].count, pending);
  await events.submitPackage({ preventDefault() {} });
  assert.deepEqual(events.created.packages.map(pack => pack.batch_allocations.map(row => [row.production_batch_id, row.quantity])), expected);
}
const incomplete = { ...merged, states: { 9: true, 10: [1] }, created: undefined };
render(75, 0, true, incomplete);
await incomplete.submitPackage({ preventDefault() {} });
assert.equal(incomplete.created, undefined);

// A successful QR change must refresh both entry counters and size balances,
// including other cached batches of this order, without invalidating other orders.
const events = {};
render(120, 60, true, events);
await events.packageChanged();
assert.deepEqual(events.refreshed.sort(), [
  "/api/production-orders/1", "/api/work-orders/3", "/api/work-orders/3/packaging-batch-progress", "/api/packages/sources/3",
].sort());
for (const key of ["/api/packages/first-grade/size-entry/1", "/api/packages/first-grade/size-entry/1?production_batch_id=2"]) {
  assert.equal(events.sizePredicate(key), true);
}
for (const key of ["/api/packages/first-grade/size-entry/10", "/api/work-orders/3", null]) {
  assert.equal(events.sizePredicate(key), false);
}

const infoSource = fs.readFileSync(new URL("../src/components/WorkOrderProductInfo.tsx", import.meta.url), "utf8");
const infoCompiled = ts.transpileModule(infoSource, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React,
} }).outputText;
const infoDeps = {
  react: React,
  "@/lib/variantDisplay": { formatModelVariantCode: value => value },
  "@/lib/errorMessages": { localizeError: value => value },
  "@/lib/modelComposition": { formatModelComposition: () => "" },
  "@/lib/modelImages": { imagePreviewHref: value => value, isPreviewModelImage: () => false, storageThumbnailUrl: value => value },
  "@/lib/orderRef": { orderReference: () => "PO-0306" },
};
const infoExports = {};
new Function("exports", "React", "require", infoCompiled)(infoExports, React, name => {
  assert.ok(name in infoDeps, `Unexpected dependency ${name}`);
  return infoDeps[name];
});
for (const actual of [590, 585, 0, 600]) {
  const html = renderToStaticMarkup(React.createElement(infoExports.default, {
    t: key => key, compact: true,
    po: { planned_quantity: 600, actual_quantity: actual, actual_cut_quantity: 600,
      actual_bundle_quantity: 590, batches: [{ planned_quantity: 684 }] },
  }));
  assert.match(html, new RegExp(`field.actualQty</div><div class="font-medium">${actual}</div>`));
}
console.log("Packaging form renders passed sewing output and remaining input, including zero and unbatched orders.");
