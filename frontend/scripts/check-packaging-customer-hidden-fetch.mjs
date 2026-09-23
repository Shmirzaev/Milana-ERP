import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/work-orders/[id]/packaging/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(
  source,
  /["'`]\/api\/customers["'`]/,
  "packaging must reuse the customer projection already returned by the sales-order detail",
);
assert.match(source, /`\/api\/work-orders\/\$\{id\}\/page-context`/);
assert.doesNotMatch(source, /mutatePo/, "packaging must revalidate its combined context only once");

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
    const data = key === "/api/work-orders/7/page-context"
      ? {
          work_order: { id: 7, production_order_id: 12, status: "new", operation: "packaging" },
          production_order: { id: 12, sales_order_id: salesOrderId, model_id: 4, items: [], batches: [] },
          sales_order: salesOrderId ? { id: 21, customer_id: 33, customer_name: "Client A", items: [] } : null,
          model: { id: 4, code: "MODEL-4", name: "Model 4" },
        }
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
    swr: { default: useSWR },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/batchSerial": { formatBatchLabel: () => "Batch", formatBatchSerial: () => "1" },
    "@/components/PackageQrSection": { default: "package-qr" },
    "@/lib/packageWorkflow": { postPackageWorkflow() {} },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/StagePipeline": { operationLabel: (value) => value, statusLabel: (value) => value },
    "@/components/WorkOrderProductInfo": { default: "product-info" },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 1, permissions: ["*"] } }) },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/numberInput": {
      numberOrFallback: (value, fallback) => Number(value || fallback),
      numberOrZero: (value) => Number(value || 0),
      parseNumberInput: Number,
    },
    "@/lib/orderRef": { orderReference: () => "PO-12" },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  const tree = loadedModule.exports.default();
  return { requests, tree };
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

const branded = renderCase(null);
assert.equal(branded.requests.filter((key) => key === "/api/work-orders/7/page-context").length, 1);
assert.equal(branded.requests.filter((key) => ["/api/work-orders/7", "/api/production-orders/12", "/api/sales-orders/21", "/api/models/4"].includes(key)).length, 0);
assert.equal(
  branded.requests.includes("/api/customers"),
  false,
  "branded packaging must not fetch an unused customer directory",
);
assert.equal(find(branded.tree, "product-info")?.props.customerName, null);

const client = renderCase(21);
assert.equal(
  client.requests.filter((key) => key === "/api/customers").length,
  0,
  "client packaging must not add a directory waterfall after sales-order resolution",
);
assert.equal(find(client.tree, "product-info")?.props.customerName, "Client A");

console.log("Packaging customer identity: branded/client rendering preserved without a directory waterfall.");
