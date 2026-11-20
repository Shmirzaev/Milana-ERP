import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = fs.readFileSync(process.env.PACKAGING_PAGE_SOURCE_FILE || new URL("../src/app/(app)/work-orders/[id]/packaging/page.tsx", import.meta.url), "utf8");
const multiNastil = {};
new Function("exports", ts.transpileModule(fs.readFileSync(new URL("../src/lib/multiNastilPackaging.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(multiNastil);
const traceLibrary = {};
new Function("exports", ts.transpileModule(fs.readFileSync(new URL("../src/lib/packageBatchTrace.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(traceLibrary);
const availabilityLibrary = {};
new Function("exports", ts.transpileModule(fs.readFileSync(new URL("../src/lib/packagingAvailabilityText.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(availabilityLibrary);
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React,
} }).outputText;

function render(sewn, remaining, batched = true, events = {}) {
  let stateIndex = 0;
  const batch = { id: 1, name: "Nastil 1", batch_no: "0306-01", planned_quantity: 684,
    sewing_output_qty: sewn, available_input_qty: remaining, packed_qty: 0, available_to_package: remaining };
  const noop = () => null;
  const deps = {
    react: { ...React, useState: initial => {
      const index = stateIndex++;
      const [value] = React.useState(events.states?.[index] ?? (index === 0
        ? (typeof initial === "object" ? { ...initial, production_batch_id: batched ? 1 : 0 } : (batched ? 1 : 0)) : initial));
      return [value, next => { (events.stateUpdates ??= {})[index] = typeof next === "function" ? next(value) : next; }];
    }, useEffect: effect => { (events.effects ??= []).push(effect); } },
    "next/navigation": { useParams: () => ({ id: "3" }) },
    swr: { useSWRConfig: () => ({ mutate: async predicate => { events.sizePredicate = predicate; } }),
      default: key => ({ mutate: async () => { if (events.refreshError) throw new Error("Refresh blocked"); (events.refreshed ??= []).push(key); }, error: key?.startsWith("/api/packages/sources/") ? events.sourceError : undefined, isLoading: !!events.sourceLoading, data:
      key?.startsWith("/api/packages/sources/") ? { items: events.sources || events.batches || [batch], unbatched_source: batched ? null : batch }
      : key?.includes("packaging-batch-progress") ? { ...batch, items: batched ? (events.batches || [batch]) : [] }
      : key?.includes("production-orders") ? { id: 1, model_id: 1, planned_quantity: 684,
        batches: batched ? [batch] : [], items: [{ size: "M", color: "white", planned_quantity: 684 }] }
      : key?.includes("work-orders") ? { id: 3, production_order_id: 1, planned_output_qty: 684, passed_qty: 0 }
      : key === "/api/customers" ? [] : undefined }) },
    "@/lib/api": { api: { openLabel: async () => { if (events.printError) throw new Error("Print blocked"); }, post: async () => { throw new Error("Separate record POST must not run"); } }, fetcher: noop },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 7 } }) },
    "@/lib/i18n": { useT: () => ({ t: (key, vars) => {
      if (events.translations) events.translations[key] = vars;
      return key;
    }, lang: "en" }) },
    "@/lib/multiNastilPackaging": multiNastil,
    "@/lib/packageBatchTrace": traceLibrary,
    "@/lib/packagingAvailabilityText": availabilityLibrary,
    "@/lib/errorMessages": { localizeError: value => value },
    "@/lib/batchSerial": { formatBatchLabel: row => row.name, formatBatchSerial: row => row.batch_no },
    "@/lib/packageWorkflow": { postPackageWorkflow: async (_path, body) => { (events.createdRequests ??= []).push(body); events.created = body; if (_path === "/api/packages/record-damage") return { id: 2, damaged_qty: body.damaged_qty }; return { id: 1, count: body.packages.length, package_ids: [1], run_no: "PRN-1" }; } },
    "@/lib/orderRef": { orderReference: () => "PO-0306" },
    "@/lib/numberInput": { numberOrZero: value => Number(value || 0), numberOrFallback: (v, f) => Number(v || f), parseNumberInput: Number },
    "@/components/StagePipeline": { operationLabel: value => value, statusLabel: value => value },
    "@/components/PackageQrSection": { default: props => { events.packageChanged = props.onChanged; return null; } },
  };
  const exports = {};
  const react = { ...React, createElement: (type, props, ...children) => {
    if (type === "button" && props.onClick && children.includes("Record damage only")) events.submitDamage = props.onClick;
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
  assert.ok(!html.includes("btn.savePackagingRecord"));
  assert.ok(!html.includes("field.inputQty"));
  assert.ok(html.includes(`Available to pack: ${remaining}`));
  assert.match(html, /min="1" max="200" step="1"/);
}
assert.match(render(585, 285, false), /Available to pack: 285/);

// Exercise the actual page submit closure, not just the planner: source selection
// must reach the atomic endpoint and must not create packs from the third Nastil.
const merged = { states: { 6: 2, 8: true, 9: [1, 2] }, batches: [], sources: [
  { id: 1, name: "Nastil A", available_to_package: 35 },
  { id: 2, name: "Nastil B", available_to_package: 40 },
  { id: 3, name: "Unselected", available_to_package: 90 },
  { id: 4, name: "Still sewing", available_to_package: 0 },
] };
const mergedHtml = render(75, 0, true, merged);
assert.match(mergedHtml, /Selected Nastils: 2/);
assert.match(mergedHtml, /aria-label="Select Still sewing" disabled=""/);
await merged.submitPackage({ preventDefault() {} });
assert.equal(merged.created.work_order_id, 3);
assert.equal(merged.created.packages.length, 2);
assert.deepEqual(merged.created.packages.map(pack => pack.items.reduce((sum, item) => sum + item.quantity, 0)), [60, 15]);
assert.deepEqual(merged.created.packages.flatMap(pack => pack.batch_allocations.map(row => [row.production_batch_id, row.quantity])), [[1, 35], [2, 25], [2, 15]]);
assert.ok(merged.created.packages.every(pack => pack.batch_allocations.every(row => row.item_breakdown === undefined)));
// Sizes still describe the package as a whole. Operators may change only batch totals.
const mixedItems = [{ model_id: 1, color: "white", size: "M", quantity: 30 }, { model_id: 1, color: "white", size: "L", quantity: 30 }];
const mixedEvent = { ...merged, created: undefined,
  states: { 1: mixedItems.map(({ size, quantity }) => ({ size, quantity })), 6: 1, 8: true, 9: [1, 2] } };
const mixedHtml = render(75, 0, true, mixedEvent);
assert.doesNotMatch(mixedHtml, /Contents by Nastil and size/);
assert.match(mixedHtml, /Adjust quantities by Nastil/);
await mixedEvent.submitPackage({ preventDefault() {} });
assert.deepEqual(mixedEvent.created.packages[0].items, mixedItems);
assert.deepEqual(mixedEvent.created.packages[0].batch_allocations.map(row => [row.production_batch_id, row.quantity]), [[1, 35], [2, 25]]);
const draftSources = [{ id: 1, available: 35, label: "A" }, { id: 2, available: 40, label: "B" }];
const plans = [{ items: mixedItems, batch_allocations: mixedEvent.created.packages[0].batch_allocations }];
const adjusted = multiNastil.applyNastilQuantities(plans, draftSources, { 0: { 1: "30", 2: "30" } });
assert.equal(adjusted.valid, true);
assert.deepEqual(adjusted.plans[0].batch_allocations.map(row => row.quantity), [30, 30]);
for (const quantities of [{ 1: "10", 2: "40" }, { 1: "20", 2: "41" }, { 1: "29.5", 2: "30.5" }]) {
  assert.equal(multiNastil.applyNastilQuantities(plans, draftSources, { 0: quantities }).valid, false);
}
const onePack = { ...merged, states: { 6: 1, 8: true, 9: [1, 2] }, created: undefined };
render(75, 0, true, onePack);
await onePack.submitPackage({ preventDefault() {} });
assert.equal(onePack.created.packages.length, 1);
assert.deepEqual(onePack.created.packages[0].batch_allocations.map(row => [row.production_batch_id, row.quantity]), [[1, 35], [2, 25]]);
// The real single-source submit must stop after the requested full or partial pack.
for (const [quantity, copies, expected] of [[300, 1, [60]], [130, 2, [60, 60]], [75, 2, [60, 15]], [75, 5, [60, 15]], [0, 1, []]]) {
  const events = { states: { 6: copies }, batches: [{ id: 1, packed_qty: quantity, available_to_package: quantity }] };
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
  const events = { states: { 6: copies, 8: true, 9: [1, 2] }, translations: {}, sources: [
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
const incomplete = { ...merged, states: { 8: true, 9: [1] }, created: undefined };
render(75, 0, true, incomplete);
await incomplete.submitPackage({ preventDefault() {} });
assert.equal(incomplete.created, undefined);

// The new damage field belongs to the same atomic action and reduces only good
// availability; it must never send a second record request.
for (const damaged of [5, 0]) {
  const events = { states: { 15: damaged }, sources: [{ id: 1, available_to_package: 95, available_input_qty: 95 }] };
  const html = render(95, 95, true, events);
  assert.ok(html.includes(`Pieces left for later: ${35 - damaged}`));
  await events.submitPackage({ preventDefault() {} });
  assert.equal(events.created.work_order_id, 3);
  assert.equal(events.created.damaged_qty ?? 0, damaged);
  assert.equal(events.created.packages.length, 1);
}
for (const states of [{ 6: 201 }, { 6: 1.5 }, { 15: 96 }, { 15: -1 }, { 15: 0.5 }]) {
  const events = { states, sources: [{ id: 1, available_to_package: 95, available_input_qty: 95 }] };
  render(95, 95, true, events); await events.submitPackage({ preventDefault() {} });
  assert.equal(events.created, undefined);
}
for (const eventFlags of [{ sourceError: new Error("Sources unavailable") }, { sourceLoading: true }]) {
  const events = { ...eventFlags }; render(95, 95, true, events);
  await events.submitPackage({ preventDefault() {} }); assert.equal(events.created, undefined);
}
for (const flags of [{ printError: true }, { refreshError: true }]) {
  const events = { ...flags }; render(95, 95, true, events);
  await events.submitPackage({ preventDefault() {} });
  assert.equal(events.createdRequests.length, 1, "A refresh/print failure must never repeat a committed write");
}

// A source disappearing during revalidation must never transfer a damage draft
// to a different Nastil. Exercise the actual page effects and refusal closure.
const moved = { states: { 0: 9, 15: 5 }, sources: [{ id: 10, available_input_qty: 95, available_to_package: 95 }] };
render(95, 95, true, moved); moved.effects.forEach(effect => effect());
assert.equal(moved.stateUpdates[0], 9);
await moved.submitPackage({ preventDefault() {} }); assert.equal(moved.created, undefined);
for (const merged of [false, true]) {
  const incomplete = { states: { 1: [{ size: "M", quantity: 60 }, { size: "L", quantity: "" }], 8: merged, 9: [1, 2] },
    sources: [{ id: 1, available_to_package: 95 }, { id: 2, available_to_package: 95 }] };
  render(190, 190, true, incomplete); await incomplete.submitPackage({ preventDefault() {} });
  assert.equal(incomplete.created, undefined, "Incomplete size rows must not disappear in mixed mode");
}
const allDamage = { states: { 15: 95 }, sources: [{ id: 1, available_to_package: 95, available_input_qty: 95 }] };
const allDamageHtml = render(95, 95, true, allDamage);
assert.match(allDamageHtml, /Record damage only/);
await allDamage.submitDamage();
assert.deepEqual(allDamage.created, { work_order_id: 3, production_batch_id: 1, damaged_qty: 95 });
assert.equal(allDamage.created.packages, undefined);
assert.equal(allDamage.stateUpdates[11].type, "success");
assert.equal(allDamage.stateUpdates[15], "");

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
console.log("PASS: direct Sewing packaging, selected batches and count, partial/unbatched balances and cache refresh; no separate record form/POST.");
