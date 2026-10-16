import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/components/DepartmentOrderList.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const dependencies = {
  react: React, "react/jsx-runtime": jsxRuntime,
  "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
  "@/components/ImageThumbnail": { default: () => null },
  "@/components/StagePipeline": { operationLabel: value => value },
  "@/lib/orderRef": { orderReference: row => row.production_no, formatOrderReference: value => value },
  "@/lib/variantDisplay": { formatVariantNumber: value => value },
};
const componentModule = { exports: {} };
new Function("require", "module", "exports", compiled)(name => {
  assert.ok(name in dependencies, name);
  return dependencies[name];
}, componentModule, componentModule.exports);
for (const operation of ["packaging", "sewing"]) {
  for (const queueKind of ["in_progress", "completed"]) {
    const html = renderToStaticMarkup(React.createElement(componentModule.exports.default, {
      rows: [{ id: 1250, production_order_id: 318, production_no: "PO-0293", operation, queueKind,
        status: queueKind, planned_output_qty: 600, passed_qty: 300 }],
      title: "Orders", emptyLabel: "Empty", t: key => key,
    }));
    const label = queueKind === "completed" && operation !== "packaging" ? "page.deptInbox.viewOrder" : "btn.open";
    const path = label === "btn.open" ? `/work-orders/1250/${operation}` : "/production-orders/318";
    assert.ok(html.includes(`href="${path}">${label}</a>`), `${operation} ${queueKind} must retain its correct action`);
  }
}
console.log("PASS: completed Packaging remains accessible; other department actions are unchanged.");
