import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const processKey = "/api/process-tracking";
const materialRequirementsKey = "/api/planning/material-requirements/12";
const source = fs.readFileSync(new URL("../src/app/(app)/sales-orders/[id]/page.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /const processesKey = so && so\.status !== "draft" \? "\/api\/process-tracking" : null;/,
  "process tracking must stay dormant for draft or unresolved orders",
);
assert.match(
  source,
  /so \? `\/api\/planning\/material-requirements\/\$\{id\}` : null/,
  "material requirements must not bypass sales-order authorization or existence resolution",
);
assert.match(
  source,
  /\{activeProcess && \([\s\S]*?page\.soDetail\.currentProductionStage[\s\S]*?<StagePipeline/,
  "the production-stage card must remain tied to a linked process",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderCase({ order, denied = false }) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: { useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}] },
    "next/navigation": { useParams: () => ({ id: "12" }) },
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: key === "/api/sales-orders/12"
            ? order
            : key === "/api/planning/material-requirements/12"
              ? []
              : key === processKey
                ? [{
                    sales_order_id: 12,
                    production_order_id: 30,
                    production_no: "PO-30",
                    current_stage: "sewing",
                    current_stage_status: "in_progress",
                    stages: [],
                    po_deadline: null,
                  }]
                : undefined,
          error: key === "/api/sales-orders/12" && denied ? new Error("403 forbidden") : undefined,
          isLoading: false,
          mutate() {},
        };
      },
    },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/components/PageHeader": { default: "page-header" },
    "@/lib/i18n": { useT: () => ({ t: (key) => key, lang: "en" }) },
    "@/components/StagePipeline": {
      default: "stage-pipeline",
      operationLabel: (value) => value,
      productionTypeLabel: (value) => value,
      statusLabel: (value) => value,
    },
    "@/lib/orderRef": { formatOrderReference: (value) => value, orderReference: () => "PO-30" },
    "@/lib/materialComposition": { formatComposition: () => "" },
    "@/lib/modelComposition": { formatModelComposition: () => "" },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  const tree = loadedModule.exports.default();
  return { requests: requests.filter(Boolean), tree };
}

function visit(tree, callback) {
  if (tree === null || tree === undefined || typeof tree === "boolean") return;
  if (Array.isArray(tree)) {
    for (const child of tree) visit(child, callback);
    return;
  }
  if (typeof tree !== "object") {
    callback(tree);
    return;
  }
  callback(tree);
  visit(tree.props?.children, callback);
}

function textContent(tree) {
  const values = [];
  visit(tree, (node) => {
    if (typeof node === "string" || typeof node === "number") values.push(String(node));
  });
  return values.join(" ");
}

const baseOrder = {
  id: 12,
  order_no: "SO-12",
  order_type: "client_order",
  status: "draft",
  total_amount: 100,
  deadline: null,
  items: [],
  printing_attachments: [],
};

const draft = renderCase({ order: baseOrder });
assert.equal(draft.requests.filter((key) => key === processKey).length, 0);
assert.equal(draft.requests.filter((key) => key === materialRequirementsKey).length, 1);
assert.match(textContent(draft.tree), /SO-12/);
assert.doesNotMatch(textContent(draft.tree), /page\.soDetail\.currentProductionStage|sewing/);

const active = renderCase({ order: { ...baseOrder, status: "confirmed" } });
assert.equal(active.requests.filter((key) => key === processKey).length, 1);
assert.equal(active.requests.filter((key) => key === materialRequirementsKey).length, 1);
assert.match(textContent(active.tree), /SO-12/);
assert.match(textContent(active.tree), /page\.soDetail\.currentProductionStage/);
assert.match(textContent(active.tree), /PO-30\s+·\s+sewing\s+·\s+in_progress/);

const denied = renderCase({ order: undefined, denied: true });
assert.equal(denied.requests.filter((key) => key === processKey).length, 0);
assert.equal(denied.requests.filter((key) => key === materialRequirementsKey).length, 0);
assert.match(textContent(denied.tree), /page\.salesOrder\.loadError/);
assert.doesNotMatch(textContent(denied.tree), /SO-12|currentProductionStage|PO-30/);

console.log("Sales-order detail: hidden process tracking and authorization-dependent material keys retain exact parity.");
