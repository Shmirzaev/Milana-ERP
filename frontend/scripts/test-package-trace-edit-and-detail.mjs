import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

function compile(file) {
  return ts.transpileModule(fs.readFileSync(new URL(file, import.meta.url), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React },
  }).outputText;
}
const library = {};
new Function("exports", compile("../src/lib/packageBatchTrace.ts"))(library);
const noop = () => null;
const items = [{ model_id: 1, color: "white", size: "M", quantity: 30 }, { model_id: 1, color: "blue", size: "L", quantity: 30 }];
const allocations = [{ production_batch_id: 11, quantity: 35, batch_no: "0306-01", item_breakdown: [{ ...items[0], quantity: 10 }, { ...items[1], quantity: 25 }] },
  { production_batch_id: 12, quantity: 25, batch_no: "0306-02", item_breakdown: [{ ...items[0], quantity: 20 }, { ...items[1], quantity: 5 }] }];
const asPlans = form => [{ items: form.items.map(item => ({ ...item, quantity: Number(item.quantity) })), batch_allocations: form.batch_allocations.map(row => ({ ...row, quantity: Number(row.quantity), label: row.batch_no })) }];
const form = { color: "white", package_type: "bag", capacity: "60", weight_kg: "", warehouse_id: "", storage_cell: "", storage_shelf: "", notes: "Metadata only", reason: "Check",
  items: items.map(item => ({ ...item, quantity: String(item.quantity) })), batch_allocations: allocations.map(row => ({ ...row, quantity: String(row.quantity) })) };
const oldPlans = asPlans(form);
const originalKey = library.packageTracePlanKey(oldPlans);
const originalDraft = library.traceDraftFromSaved(oldPlans);

function renderEdit(currentForm, trace, events) {
  let stateIndex = 0;
  const state = { 2: { id: 9, model_id: 1 }, 3: currentForm, 9: trace };
  const react = { ...React, createElement(type, props, ...children) {
    if (type === "form" && props.onSubmit) events.submit = props.onSubmit;
    return React.createElement(type, props, ...children);
  } };
  const deps = {
    react: { ...React, useState(initial) { const index = stateIndex++; return [state[index] ?? initial, value => { (events.states ??= {})[index] = value; }]; } },
    "next/link": { default: ({ children }) => children },
    swr: { default: key => ({ data: key?.includes("change-requests") ? [] : { rows: [], total: 0 }, mutate: async () => {} }) },
    "@/lib/api": { api: { post: async (path, body) => { events.request = { path, body }; } }, fetcher: noop },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 1 } }) },
    "@/lib/i18n": { useT: () => ({ lang: "en", t: key => key }) },
    "@/lib/packageBatchTrace": library,
    "@/lib/packageWorkflow": { packageWorkflowCopy: { en: new Proxy({}, { get: (_, key) => String(key) }) }, postPackageWorkflow: noop },
    "@/components/StagePipeline": { statusLabel: value => value },
    "@/components/Modal": { default: ({ children }) => children },
  };
  const output = {};
  new Function("exports", "React", "require", compile("../src/components/PackageQrSection.tsx"))(output, react, name => {
    if (name in deps) return deps[name];
    assert.ok(name.startsWith("@/components/"), name); return { default: noop };
  });
  renderToStaticMarkup(React.createElement(output.default, { productionOrderId: 1 }));
}

for (const unknown of [false, true]) {
  const control = unknown ? { ...form, batch_allocations: form.batch_allocations.map(row => ({ ...row, item_breakdown: null })) } : form;
  const event = {};
  renderEdit(control, { key: originalKey, originalKey, values: unknown ? {} : originalDraft, touched: false }, event);
  await event.submit({ preventDefault() {} });
  assert.equal(event.request.path, "/api/packages/9/change-requests");
  assert.equal(event.request.body.payload.batch_allocations, undefined, "Metadata-only edits must preserve attribution in the server");
  assert.deepEqual(event.request.body.payload.items.map(item => item.color), ["white", "blue"], "Metadata must not repaint multi-color contents");
}
const changed = { ...form, items: [{ ...form.items[0], quantity: "20" }, { ...form.items[1], quantity: "40" }] };
const changedPlans = asPlans(changed);
const key = library.packageTracePlanKey(changedPlans);
const missing = {};
renderEdit(changed, { key: originalKey, originalKey, values: originalDraft, touched: false }, missing);
await missing.submit({ preventDefault() {} });
assert.equal(missing.request, undefined, "Changed physical contents cannot reuse stale source cells");
const replacement = {};
for (const [batch, m, l] of [[11, 10, 25], [12, 10, 15]]) {
  replacement[library.traceCellKey(0, batch, items[0])] = String(m);
  replacement[library.traceCellKey(0, batch, items[1])] = String(l);
}
const corrected = {};
renderEdit(changed, { key, originalKey, values: replacement, touched: true }, corrected);
await corrected.submit({ preventDefault() {} });
assert.deepEqual(corrected.request.body.payload.batch_allocations.map(row => row.item_breakdown.map(item => item.quantity)), [[10, 25], [10, 15]]);

// Render the actual package detail page: business batch numbers and legacy
// uncertainty must survive reopening, rather than disappearing in a total.
for (const unknown of [false, true]) {
  const p = { id: 9, package_no: "PKG-9", status: "packed", items: items.map((item, index) => ({ ...item, id: index + 1 })), batch_allocations: allocations.map(row => ({ ...row, item_breakdown: unknown ? null : row.item_breakdown })) };
  const deps = {
    "next/link": { default: ({ children }) => children },
    "next/navigation": { useParams: () => ({ id: "9" }) },
    swr: { default: () => ({ data: p }) },
    "@/lib/auth": { can: () => false, useMe: () => ({ me: { id: 1 } }) },
    "@/lib/i18n": { useT: () => ({ lang: "en", t: key => key }) },
    "@/lib/api": { api: {}, fetcher: noop },
    "@/lib/packageBatchTrace": library,
    "@/lib/packageIdentity": { packageIdentityText: { en: {} }, sewingFactoryLabel: () => "Milana" },
    "@/lib/variantDisplay": { formatModelVariantCode: () => "Model" },
    "@/lib/firstGradeText": { firstGradeText: { en: {} } },
    "@/components/StagePipeline": { statusLabel: value => value },
  };
  const output = {};
  new Function("exports", "React", "require", compile("../src/app/(app)/packages/[id]/page.tsx"))(output, React, name => {
    if (name in deps) return deps[name];
    assert.ok(name.startsWith("@/components/"), name); return { default: noop };
  });
  const html = renderToStaticMarkup(React.createElement(output.default));
  assert.ok(html.includes("0306-01") && html.includes("0306-02"));
  assert.equal(html.includes(library.packageBatchTraceText.en.unknown), unknown);
  if (!unknown) assert.match(html, /white<\/td><td>M<\/td><td class="tabular-nums">10/);
}
console.log("PASS: actual correction submit preserves metadata/multi-color/legacy controls, requires fresh exact contents, and detail renders exact vs unknown provenance.");
