import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/work-orders/[id]/packaging/page.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React,
} }).outputText;

function render(sewn, remaining, batched = true) {
  let stateIndex = 0;
  const batch = { id: 1, name: "Nastil 1", batch_no: "0306-01", planned_quantity: 684,
    sewing_output_qty: sewn, available_input_qty: remaining, packed_qty: 0, available_to_package: 0 };
  const noop = () => null;
  const deps = {
    react: { ...React, useState: initial => React.useState(stateIndex++ === 0
      ? { ...initial, production_batch_id: batched ? 1 : 0 } : initial) },
    "next/navigation": { useParams: () => ({ id: "3" }) },
    swr: { default: key => ({ mutate: noop, data:
      key?.includes("packaging-batch-progress") ? { ...batch, items: batched ? [batch] : [] }
      : key?.includes("production-orders") ? { id: 1, planned_quantity: 684,
        batches: batched ? [batch] : [], items: [{ size: "M", color: "white", planned_quantity: 684 }] }
      : key?.includes("work-orders") ? { id: 3, production_order_id: 1, planned_output_qty: 684, passed_qty: 0 }
      : key === "/api/customers" ? [] : undefined }) },
    "@/lib/api": { api: {}, fetcher: noop },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: {} }) },
    "@/lib/i18n": { useT: () => ({ t: key => key }) },
    "@/lib/errorMessages": { localizeError: value => value },
    "@/lib/batchSerial": { formatBatchLabel: row => row.name, formatBatchSerial: row => row.batch_no },
    "@/lib/packageWorkflow": { postPackageWorkflow: noop },
    "@/lib/orderRef": { orderReference: () => "PO-0306" },
    "@/lib/numberInput": { numberOrZero: value => Number(value || 0), numberOrFallback: (v, f) => Number(v || f), parseNumberInput: Number },
    "@/components/StagePipeline": { operationLabel: value => value, statusLabel: value => value },
  };
  const exports = {};
  new Function("exports", "React", "require", compiled)(exports, React, name => {
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
