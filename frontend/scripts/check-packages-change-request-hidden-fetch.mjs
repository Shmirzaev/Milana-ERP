import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const pendingPrefix = "/api/packages/change-requests?";
const source = fs.readFileSync(new URL("../src/app/(app)/packages/page.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /const pendingRequestsKey = Object\.values\(expandedGroups\)\.some\(Boolean\)\s*\? `\/api\/packages\/change-requests\?status=pending&packaging_department_code=\$\{packagingDepartment\}`\s*: null;/,
  "pending package changes must wait for an expanded package group",
);
assert.match(source, /const pending = pendingByPackage\.get\(Number\(p\.id\)\);/, "expanded rows must retain pending request lookup");
assert.match(source, /pending\.request_type === "delete" \? t\("page\.packages\.pendingDelete"\) : t\("page\.packages\.pendingEdit"\)/, "pending request labels must remain intact");

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

const packagePage = {
  rows: [{
    id: 71,
    package_no: "PKG-71",
    barcode: "PACKAGE:71",
    production_order_id: 9,
    production_no: "PO-9",
    sales_order_id: 4,
    sales_order_no: "SO-4",
    customer_name: "Client Four",
    order_type: "client_order",
    model_id: 12,
    color: "Navy",
    total_quantity: 30,
    storage_cell: "A-01",
    storage_shelf: "S1",
    status: "packed",
  }],
  total: 1,
};

function createHarness({ denied = false } = {}) {
  const requests = [];
  const states = [];
  let stateCursor = 0;
  const jsx = (type, props) => ({ type, props: props || {} });
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      Fragment: "fragment",
      useMemo: (calculate) => calculate(),
      useState(initial) {
        const index = stateCursor++;
        if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
        return [states[index], (next) => {
          states[index] = typeof next === "function" ? next(states[index]) : next;
        }];
      },
    },
    swr: {
      default: (key) => {
        requests.push(key);
        if (key?.startsWith(pendingPrefix)) {
          return { data: [{ id: 501, package_id: 71, request_type: "edit" }], mutate: async () => {} };
        }
        if (key?.startsWith("/api/packages?")) {
          return { data: denied ? undefined : packagePage, error: denied ? new Error("403 forbidden") : undefined, mutate: async () => {} };
        }
        return { data: undefined, mutate: async () => {} };
      },
    },
    "next/link": { default: "link" },
    "next/navigation": { useSearchParams: () => new URLSearchParams() },
    "@/lib/api": { api: { openLabel() {}, get: async () => ({}), post: async () => ({}) }, fetcher() {} },
    "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 1, permissions: ["management.approve"] } }) },
    "@/components/ConfirmDialog": { default: "confirm-dialog" },
    "@/components/Modal": { default: "modal" },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/PaginationControls": { default: "pagination-controls" },
    "@/components/StagePipeline": { productionTypeLabel: (value) => value, statusLabel: (value) => value },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/orderRef": { orderReference: (row) => row.sales_order_no || row.production_no || "-" },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);

  return {
    requests,
    render() {
      stateCursor = 0;
      return loadedModule.exports.default();
    },
  };
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

function find(tree, predicate) {
  let result;
  visit(tree, (node) => {
    if (result === undefined && typeof node === "object" && predicate(node)) result = node;
  });
  return result;
}

const active = createHarness();
let activeTree = active.render();
assert.equal(active.requests.filter((key) => key?.startsWith(pendingPrefix)).length, 0);
assert.match(textContent(activeTree), /PKG-71/);
assert.doesNotMatch(textContent(activeTree), /page\.packages\.pendingEdit/);

const openButton = find(activeTree, (node) => node.type === "button" && textContent(node) === "btn.open");
assert.ok(openButton, "the real package group open control must render");
openButton.props.onClick();
activeTree = active.render();
assert.equal(active.requests.filter((key) => key?.startsWith(pendingPrefix)).length, 1);
assert.match(textContent(activeTree), /PKG-71/);
assert.match(textContent(activeTree), /page\.packages\.pendingEdit/);
const editButton = find(activeTree, (node) => node.type === "button" && textContent(node) === "common.edit");
assert.equal(editButton?.props.disabled, true, "pending package edits must remain disabled");

const denied = createHarness({ denied: true });
const deniedTree = denied.render();
assert.equal(denied.requests.filter((key) => key?.startsWith(pendingPrefix)).length, 0);
assert.match(textContent(deniedTree), /page\.packages\.empty/);
assert.doesNotMatch(textContent(deniedTree), /PKG-71|page\.packages\.pendingEdit/);

console.log("Packages pending changes: collapsed/denied key 1 -> 0; expanded group remains exactly 1 with pending controls intact.");
