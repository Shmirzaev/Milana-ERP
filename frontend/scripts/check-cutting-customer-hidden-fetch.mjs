import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/work-orders/[id]/cutting/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(
  source,
  /["'`]\/api\/customers["'`]/,
  "cutting must reuse the projected customer instead of fetching the full directory",
);
assert.match(source, /`\/api\/work-orders\/\$\{id\}\/page-context`/);
assert.doesNotMatch(source, /mutatePo/, "cutting must revalidate its combined context only once per mutation");
assert.match(
  source,
  /canReadCustomers[\s\S]*?so\.customer\?\.name \|\| so\.customer_name[\s\S]*?: `#\$\{so\.customer_id\}`/,
  "projected names must retain the restricted-user ID-only fallback",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderCase({ salesOrderId, authorized = true }) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const useSWR = (key) => {
    requests.push(key);
    const data = key === "/api/work-orders/7/page-context"
      ? {
          work_order: { id: 7, production_order_id: 12, status: "new", department_id: 1 },
          production_order: { id: 12, sales_order_id: salesOrderId, model_id: 4, batches: [], source_type: "standard" },
          sales_order: salesOrderId ? { id: 21, customer_id: 33, customer_name: "Client A", order_no: "SO-21" } : null,
          model: { id: 4, code: "MODEL-4", name: "Model 4", bom: [], sizes: [], colors: [] },
        }
            : key === "/api/departments"
                ? []
                : typeof key === "string" && key.startsWith("/api/bundles?")
                  ? { rows: [], total: 0 }
                  : typeof key === "string" && key.includes("cutting-batch-progress")
                    ? { items: [] }
                    : typeof key === "string" && key.includes("replacement-status")
                      ? { items: [], open_qty: 0 }
                      : typeof key === "string" && key.startsWith("/api/inventory/batches?")
                        ? []
                        : typeof key === "string" && key.startsWith("/api/cutting-passports?")
                          ? []
                          : undefined;
    return { data, error: undefined, isLoading: false, mutate() {} };
  };
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      Fragment: "fragment",
      useEffect() {},
      useMemo: (calculate) => calculate(),
      useRef: (initial) => ({ current: initial }),
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    },
    "next/navigation": { useParams: () => ({ id: "7" }) },
    swr: { default: useSWR, useSWRConfig: () => ({ mutate() {} }) },
    "@/components/CuttingMaterialBatchEditor": { default: "material-batch-editor" },
    "lucide-react": { ChevronDown: "chevron-down", ChevronRight: "chevron-right" },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/batchSerial": { formatBatchLabel: () => "Batch", formatBatchSerial: () => "1" },
    "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => true, notify: async () => {} }) },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/StagePipeline": { operationLabel: (value) => value, statusLabel: (value) => value },
    "@/components/WorkOrderProductInfo": { default: "product-info" },
    "@/lib/auth": { can: () => authorized, useMe: () => ({ me: { id: 7 } }) },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/orderRef": { orderReference: () => "SO-21" },
    "@/lib/numberInput": {
      numberOrFallback: (value, fallback) => Number(value || fallback),
      numberOrZero: (value) => Number(value || 0),
    },
    "@/lib/cuttingPassportAutofill": {
      beikaKgFromPassport: () => 0,
      cuttingPassportAutofillValues: () => ({}),
      wasteKgFromPassport: () => 0,
    },
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

const unresolved = renderCase({ salesOrderId: null });
assert.equal(unresolved.requests.filter((key) => key === "/api/work-orders/7/page-context").length, 1);
assert.equal(unresolved.requests.filter((key) => ["/api/work-orders/7", "/api/production-orders/12", "/api/sales-orders/21", "/api/models/4"].includes(key)).length, 0);
assert.equal(unresolved.requests.filter((key) => key === "/api/customers").length, 0);
assert.equal(find(unresolved.tree, "product-info")?.props.customerName, null);

const unauthorized = renderCase({ salesOrderId: 21, authorized: false });
assert.equal(
  unauthorized.requests.filter((key) => key === "/api/customers").length,
  0,
  "customer authorization must remain enforced",
);
assert.equal(find(unauthorized.tree, "product-info")?.props.customerName, "#33");

const client = renderCase({ salesOrderId: 21 });
assert.equal(
  client.requests.filter((key) => key === "/api/customers").length,
  0,
  "an authorized resolved client work order must render the projection without a directory request",
);
assert.equal(find(client.tree, "product-info")?.props.customerName, "Client A");

console.log("Cutting customers: unresolved/unauthorized parity and projected authorized names need zero directory requests.");
