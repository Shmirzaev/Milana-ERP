import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/work-orders/[id]/sewing/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(
  source,
  /["'`]\/api\/customers["'`]/,
  "sewing must reuse the customer projection already returned by the sales-order detail",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderCase(salesOrderId) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const useSWR = (key) => {
    requests.push(key);
    const data = key === "/api/work-orders/7"
      ? { id: 7, production_order_id: 12, status: "new", sewing_flow_id: 1 }
      : key === "/api/production-orders/12"
        ? { id: 12, sales_order_id: salesOrderId, model_id: 4, batches: [] }
        : key === "/api/sales-orders/21"
          ? { id: 21, customer_id: 33, customer_name: "Client A", order_no: "SO-21" }
          : key === "/api/models/4"
            ? { id: 4, code: "MODEL-4", name: "Model 4" }
            : key === "/api/sewing-flows"
              ? [{ id: 1, code: "LINE-1", name: "Line 1" }]
              : key === "/api/work-orders/7/assignments"
                ? []
                : key === "/api/work-orders/7/sewing-batch-progress"
                  ? { items: [] }
                  : key === "/api/work-orders/7/replacement-status"
                    ? { items: [], open_qty: 0 }
                    : undefined;
    return { data, mutate() {} };
  };
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect() {},
      useMemo: (calculate) => calculate(),
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    },
    "next/navigation": { useParams: () => ({ id: "7" }) },
    swr: { default: useSWR, mutate() {} },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/batchSerial": { formatBatchLabel: () => "Batch", formatBatchSerial: () => "1" },
    "@/components/SewingRecordHistory": { default: "sewing-history" },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/DefectReasonSelect": { default: "defect-reason" },
    "@/components/StagePipeline": { operationLabel: (value) => value, statusLabel: (value) => value },
    "@/components/WorkOrderProductInfo": { default: "product-info" },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/numberInput": {
      numberOrZero: (value) => Number(value || 0),
      parseNumberInput: Number,
    },
    "@/lib/orderRef": { orderReference: () => "SO-21" },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  return { requests, tree: loadedModule.exports.default() };
}

function find(tree, type) {
  if (!tree || typeof tree !== "object") return null;
  if (tree.type === type) return tree;
  const children = Array.isArray(tree.props?.children) ? tree.props.children : [tree.props?.children];
  for (const child of children) {
    const match = find(child, type);
    if (match) return match;
  }
  return null;
}

const warehouseOrBranded = renderCase(null);
assert.equal(
  warehouseOrBranded.requests.filter((key) => key === "/api/customers").length,
  0,
  "a work order without a sales-order customer must not fetch the customer directory",
);
assert.equal(find(warehouseOrBranded.tree, "product-info")?.props.customerName, null);

const client = renderCase(21);
assert.equal(
  client.requests.filter((key) => key === "/api/customers").length,
  0,
  "a resolved client work order must render the projection without a directory request",
);
assert.equal(find(client.tree, "product-info")?.props.customerName, "Client A");

console.log("Sewing customer identity: unresolved/client rendering preserved without a directory waterfall.");
