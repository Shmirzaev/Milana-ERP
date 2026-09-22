import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const sewingFlowKey = "/api/sewing-flows";
const source = fs.readFileSync(new URL("../src/app/(app)/work-orders/page.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /const sewingFlowKey = data\?\.some\(\(workOrder\) => workOrder\.sewing_flow_id\) \? "\/api\/sewing-flows" : null;/,
  "the sewing-line directory must depend on a loaded row that references it",
);
assert.match(
  source,
  /w\.sewing_flow_id\s*\? sewingFlowById\.get\(w\.sewing_flow_id\)\?\.name \|\| `#\$\{w\.sewing_flow_id\}`\s*: "—"/,
  "line labels and their id fallback must remain unchanged",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderCase(workOrders) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect() {},
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    },
    "next/link": { default: "link" },
    "next/navigation": { useSearchParams: () => ({ get: () => null }) },
    swr: {
      default: (key) => {
        requests.push(key);
        const data = key === "/api/departments"
          ? [{ id: 1, code: "CUT", name: "Cutting" }]
          : key === "/api/work-orders"
            ? workOrders
            : key === sewingFlowKey
              ? [{ id: 7, name: "Line Seven" }]
              : key === "/api/process-tracking"
                ? []
                : undefined;
        return { data };
      },
    },
    "@/lib/api": { fetcher() {} },
    "@/components/PageHeader": { default: "page-header" },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/components/StagePipeline": {
      default: "stage-pipeline",
      operationLabel: (value) => value,
      statusLabel: (value) => value,
    },
    "@/lib/orderRef": { orderReference: (row, fallback) => row.order_no || fallback },
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

const withoutLine = renderCase([{
  id: 10,
  production_order_id: 20,
  order_no: "PO-20",
  operation: "cutting",
  status: "in_progress",
  actual_input_qty: 12,
  actual_output_qty: 10,
  failed_qty: 2,
  deadline: null,
  sewing_flow_id: null,
}]);
assert.equal(withoutLine.requests.filter((key) => key === sewingFlowKey).length, 0);
assert.match(textContent(withoutLine.tree), /PO-20/);
assert.match(textContent(withoutLine.tree), /—/);

const withLine = renderCase([{
  id: 11,
  production_order_id: 21,
  order_no: "PO-21",
  operation: "sewing",
  status: "in_progress",
  actual_input_qty: 20,
  actual_output_qty: 18,
  failed_qty: 2,
  deadline: null,
  sewing_flow_id: 7,
}]);
assert.equal(withLine.requests.filter((key) => key === sewingFlowKey).length, 1);
assert.match(textContent(withLine.tree), /PO-21/);
assert.match(textContent(withLine.tree), /Line Seven/);

const deniedOrEmpty = renderCase(undefined);
assert.equal(deniedOrEmpty.requests.filter((key) => key === sewingFlowKey).length, 0);
assert.doesNotMatch(textContent(deniedOrEmpty.tree), /PO-20|PO-21|Line Seven/);
assert.match(textContent(deniedOrEmpty.tree), /page\.wo\.pipeline/);

console.log("Work-order sewing lines: unused/denied key 1 -> 0; referenced-line key remains exactly 1.");
