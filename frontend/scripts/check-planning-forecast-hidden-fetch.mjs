import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const forecastKey = "/api/forecasting/branded-stock-suggestions";
const source = fs.readFileSync(new URL("../src/app/(app)/planning/page.tsx", import.meta.url), "utf8");
assert.match(
  source,
  /!brandedOnly && canViewForecasting \? "\/api\/forecasting\/branded-stock-suggestions" : null/,
  "forecast suggestions must depend on the visible planning route and permission",
);
assert.match(
  source,
  /\{!brandedOnly \? \([\s\S]*?forecastSuggestions[\s\S]*?\) : null\}/,
  "forecast suggestions must remain rendered only in the standard planning branch",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderCase({ path, authorized }) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const useSWR = (key) => {
    requests.push(key);
    const data = key === "/api/dashboard/planning"
      ? {}
      : key === "/api/sales-orders?order_type=client_order&page_size=200"
        ? []
        : key === "/api/production-orders?page_size=100"
          ? []
          : key === "/api/brands"
            ? []
            : key === "/api/inventory/batches?group=materials&hide_empty=true&page_size=1000"
              ? []
              : key === "/api/planning/branded-orders"
                ? []
                : key === forecastKey
                  ? [{ model_id: 4, model_code: "FORECAST-MODEL", color: "blue", size: "48", suggested_quantity: 120, unit: "pcs" }]
                  : undefined;
    return { data, mutate: async () => {} };
  };
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect() {},
      useMemo: (calculate) => calculate(),
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    },
    "@/lib/orderRef": { formatOrderReference: (value) => value },
    "next/link": { default: "link" },
    "next/navigation": { usePathname: () => path, useSearchParams: () => ({ get: () => null }) },
    swr: { default: useSWR },
    "lucide-react": {
      PackageCheck: "package-check",
      Pencil: "pencil",
      Plus: "plus",
      RotateCcw: "rotate",
      Trash2: "trash",
    },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/lib/auth": { can: () => authorized, useMe: () => ({ me: { id: 7 } }) },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/BrandedOrderHistory": { default: "branded-history" },
    "@/components/Modal": { default: "modal" },
    "@/components/SearchableSelect": { default: "searchable-select" },
    "@/components/BrandedModelVariantSelect": { default: "model-variant-select" },
    "@/components/StagePipeline": { statusLabel: (value) => value },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/garmentSizes": { GARMENT_SIZE_OPTIONS: ["46", "48"] },
    "@/lib/numberInput": {
      numberOrFallback: (value, fallback) => Number(value || fallback),
      numberOrZero: (value) => Number(value || 0),
      parseNumberInput: (value) => value,
    },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  return { requests, tree: loadedModule.exports.default() };
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

const branded = renderCase({ path: "/planning/branded-stock", authorized: true });
assert.equal(
  branded.requests.filter((key) => key === forecastKey).length,
  0,
  "the branded-only route must not request its hidden standard-planning forecast card",
);
assert.doesNotMatch(textContent(branded.tree), /FORECAST-MODEL/);

const standard = renderCase({ path: "/planning", authorized: true });
assert.equal(
  standard.requests.filter((key) => key === forecastKey).length,
  1,
  "authorized standard planning must request forecast suggestions exactly once",
);
assert.match(textContent(standard.tree), /FORECAST-MODEL/);

const denied = renderCase({ path: "/planning", authorized: false });
assert.equal(denied.requests.filter((key) => key === forecastKey).length, 0);
assert.doesNotMatch(textContent(denied.tree), /FORECAST-MODEL/);

console.log("Planning forecast: branded route requests 1 -> 0; standard authorized remains 1; denial remains 0.");
