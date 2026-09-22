import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const salesDirectoryKey = "/api/sales-orders?page_size=500";
const source = fs.readFileSync(new URL("../src/app/(app)/production-orders/[id]/page.tsx", import.meta.url), "utf8");
assert.match(
  source,
  /useSWR<SalesOrderSummary\[\]>\(\s*canEditSummary && summaryEditing \? "\/api\/sales-orders\?page_size=500" : null,\s*fetcher,\s*\)/,
  "the sales-order directory must depend on the authorized summary editor",
);
assert.match(
  source,
  /\{summaryEditing \? \([\s\S]*?salesOrders\?\.map/,
  "the sales-order directory must remain scoped to the active summary editor",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function createHarness(authorized) {
  const jsx = (type, props) => ({ type, props: props || {} });
  const states = [];
  let stateCursor = 0;
  let dirty = false;
  let requests = [];

  function useState(initial) {
    const index = stateCursor++;
    if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
    return [states[index], (next) => {
      const value = typeof next === "function" ? next(states[index]) : next;
      if (!Object.is(value, states[index])) dirty = true;
      states[index] = value;
    }];
  }

  function useSWR(key) {
    requests.push(key);
    const data = key === "/api/production-orders/12"
      ? {
          id: 12,
          production_no: "PO-12",
          sales_order_id: 21,
          model_id: 4,
          model_code: "MODEL-4",
          model_name: "Model 4",
          status: "new",
          source_type: "standard",
          planned_quantity: 100,
          work_orders: [],
          batches: [],
          items: [],
        }
      : key === "/api/production-orders/12/material-reservation-status"
        ? undefined
        : key === "/api/sewing-flows"
          ? []
          : key === "/api/sewing-flows/utilization-snapshot"
            ? []
            : key === "/api/users"
              ? []
              : key === "/api/models/4"
                ? { id: 4, code: "MODEL-4", name: "Model 4" }
                : key === salesDirectoryKey
                  ? [{ id: 21, order_no: "SO-21", customer_name: "Client A" }]
                  : undefined;
    return { data, error: undefined, isLoading: false, mutate() {} };
  }

  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: { useState },
    "next/navigation": { useParams: () => ({ id: "12" }) },
    swr: { default: useSWR },
    "next/link": { default: "link" },
    "lucide-react": { PackageCheck: "package-check", RotateCcw: "rotate" },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/components/ModelAsyncSelect": { default: "model-select" },
    "@/components/ProductionOrderSizePlan": { default: "size-plan" },
    "@/lib/batchSerial": { formatBatchLabel: () => "Batch" },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/Modal": { default: "modal" },
    "@/components/StagePipeline": {
      operationLabel: (value) => value,
      productionTypeLabel: (value) => value,
      statusLabel: (value) => value,
    },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/auth": { can: () => authorized, useMe: () => ({ me: { id: 7 } }) },
    "@/lib/orderRef": { formatOrderReference: (value) => value, orderReference: () => "PO-12" },
    "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => true, notify: async () => {} }) },
    "@/lib/materialComposition": { formatComposition: () => "-" },
    "@/lib/modelComposition": { formatModelComposition: () => "-" },
    "@/lib/modelImages": { imagePreviewHref: (value) => value, storageThumbnailUrl: (value) => value },
    "@/lib/numberInput": { numberOrZero: (value) => Number(value || 0), parseNumberInput: Number },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  const Page = loadedModule.exports.default;

  function render() {
    dirty = false;
    stateCursor = 0;
    requests = [];
    const tree = Page();
    return { tree, requests: [...requests], dirty };
  }

  return { render };
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

function find(tree, predicate) {
  let match = null;
  visit(tree, (node) => {
    if (!match && typeof node === "object" && predicate(node)) match = node;
  });
  return match;
}

function textContent(tree) {
  const values = [];
  visit(tree, (node) => {
    if (typeof node === "string" || typeof node === "number") values.push(String(node));
  });
  return values.join(" ");
}

const authorized = createHarness(true);
const closed = authorized.render();
assert.equal(closed.requests.filter((key) => key === salesDirectoryKey).length, 0);
assert.doesNotMatch(textContent(closed.tree), /Client A/);
const editButton = find(closed.tree, (node) => node.type === "button" && node.props?.children === "btn.edit");
assert.ok(editButton, "the authorized summary edit action must render");
editButton.props.onClick();

const open = authorized.render();
assert.equal(
  open.requests.filter((key) => key === salesDirectoryKey).length,
  1,
  "the open summary editor must request the sales-order directory exactly once",
);
assert.match(textContent(open.tree), /Client A/);

const denied = createHarness(false).render();
assert.equal(denied.requests.filter((key) => key === salesDirectoryKey).length, 0);
assert.equal(
  find(denied.tree, (node) => node.type === "button" && node.props?.children === "btn.edit"),
  null,
  "unauthorized users must retain no summary edit action",
);

console.log("Production-order sales directory: closed requests 1 -> 0; open editor remains 1; denial remains 0.");
