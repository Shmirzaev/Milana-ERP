import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/sales-orders/page.tsx", import.meta.url), "utf8");

assert.doesNotMatch(
  source,
  /["'`]\/api\/customers["'`]/,
  "the list payload already projects customer names, so the page must not fetch the full directory",
);
assert.match(
  source,
  /const customerName = \(order: SO\) => order\.customer\?\.name \|\| order\.customer_name;/,
  "the page must resolve names from the existing sales-order projection",
);
assert.match(
  source,
  /customerName\(o\) \?\? t\("sales\.unknownCustomer"\)/,
  "the page must preserve its existing missing-customer fallback",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderCase(pageData) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect() {},
      useMemo: (calculate) => calculate(),
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    },
    "next/navigation": { useSearchParams: () => ({ get: () => null }) },
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: key?.startsWith("/api/sales-orders?")
            ? pageData
            : undefined,
          isLoading: false,
          mutate() {},
        };
      },
    },
    "lucide-react": {
      Download: "download",
      Filter: "filter",
      MoreHorizontal: "more",
      Plus: "plus",
      Search: "search",
      X: "x",
    },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/PaginationControls": { default: "pagination" },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/components/StagePipeline": { statusLabel: (value) => value },
    "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => false, notify: async () => {} }) },
    "@/lib/orderRef": { formatOrderReference: (value) => value },
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

const clientOrder = {
  id: 12,
  order_no: "SO-12",
  customer_id: 9,
  customer_name: "Customer Nine",
  order_type: "client_order",
  status: "confirmed",
  deadline: null,
  total_amount: 1200,
  notes: null,
};
const active = renderCase({ rows: [clientOrder], total: 1 });
assert.equal(active.requests.filter((key) => key === "/api/customers").length, 0);
assert.match(textContent(active.tree), /SO-12/);
assert.match(textContent(active.tree), /Customer Nine/);

const branded = renderCase({
  rows: [
    {
      ...clientOrder,
      id: 13,
      order_no: "SO-13",
      customer_id: null,
      customer_name: null,
      order_type: "branded_stock_sale",
    },
  ],
  total: 1,
});
assert.equal(branded.requests.filter((key) => key === "/api/customers").length, 0);
assert.match(textContent(branded.tree), /SO-13/);
assert.match(textContent(branded.tree), /sales\.unknownCustomer/);

const deniedOrEmpty = renderCase(undefined);
assert.equal(deniedOrEmpty.requests.filter((key) => key === "/api/customers").length, 0);
assert.doesNotMatch(textContent(deniedOrEmpty.tree), /SO-12|Customer Nine/);
assert.match(textContent(deniedOrEmpty.tree), /sales\.noMatch/);

console.log("Sales-order customers: projected names render with zero full-directory requests.");
