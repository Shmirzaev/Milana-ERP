import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/work-orders/[id]/cutting/page.tsx", import.meta.url), "utf8");
assert.match(
  source,
  /useSWR<any\[\]>\(\s*canReadCustomers && so\?\.customer_id \? "\/api\/customers" : null,\s*fetcher,\s*\)/,
  "the authorized customer directory must depend on a resolved sales-order customer",
);
assert.equal(
  [...source.matchAll(/\bcustomers\b/g)].length,
  5,
  "customers must remain limited to permission, SWR, and customer-name mapping",
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
    const data = key === "/api/work-orders/7"
      ? { id: 7, production_order_id: 12, status: "new", department_id: 1 }
      : key === "/api/production-orders/12"
        ? { id: 12, sales_order_id: salesOrderId, model_id: 4, batches: [], source_type: "standard" }
        : key === "/api/sales-orders/21"
          ? { id: 21, customer_id: 33, order_no: "SO-21" }
          : key === "/api/models/4"
            ? { id: 4, code: "MODEL-4", name: "Model 4", bom: [], sizes: [], colors: [] }
            : key === "/api/customers"
              ? [{ id: 33, name: "Client A" }]
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
  1,
  "an authorized resolved client work order must fetch the directory exactly once",
);
assert.equal(find(client.tree, "product-info")?.props.customerName, "Client A");

console.log("Cutting customer directory: unresolved requests 1 -> 0; authorized client remains 1; denial remains 0.");
