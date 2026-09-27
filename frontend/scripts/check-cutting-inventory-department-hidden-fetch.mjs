import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const departmentKey = "/api/departments";
const source = fs.readFileSync(new URL("../src/app/(app)/cutting-inventory/page.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /const departmentDirectoryKey = rows\.some\(\(row\) => row\.next_department_id != null\) \? "\/api\/departments" : null;/,
  "the department directory must depend on returned bundles carrying department references",
);
assert.match(source, /destinationLabel\(row, departmentById, t\)/, "expanded bundle destination labels must remain intact");

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function bundle(overrides = {}) {
  return {
    id: 31,
    bundle_no: "B-31",
    barcode: "BUNDLE:31",
    production_order_id: 8,
    production_no: "PO-8",
    production_batch_id: 3,
    batch_label: "BATCH-3",
    model_id: 11,
    model_code: "MODEL-11",
    color: "Navy",
    size: "M",
    quantity: 25,
    status: "created",
    next_department_id: 4,
    ...overrides,
  };
}

function createHarness(rows, { denied = false } = {}) {
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
        if (key === departmentKey) {
          return { data: [{ id: 4, code: "PRT", name: "Printing" }] };
        }
        if (key?.startsWith("/api/bundles/cutting-inventory?")) {
          return {
            data: denied ? undefined : { rows, total: rows.length, total_quantity: 25, total_orders: rows.length ? 1 : 0 },
            error: denied ? new Error("403 forbidden") : undefined,
            isLoading: false,
            mutate: async () => {},
          };
        }
        return { data: undefined, isLoading: false, mutate: async () => {} };
      },
    },
    "next/link": { default: "link" },
    "next/navigation": { useSearchParams: () => new URLSearchParams() },
    "lucide-react": Object.fromEntries([
      "ChevronDown", "ChevronRight", "QrCode", "RefreshCw", "Search", "X",
    ].map((name) => [name, name])),
    "@/components/PageHeader": { default: "page-header" },
    "@/components/PaginationControls": { default: "pagination-controls" },
    "@/components/FabricThumbnail": { default: "fabric-thumbnail" },
    "@/components/StagePipeline": { statusLabel: (value) => value },
    "@/lib/api": { api: { openLabel() {} }, fetcher() {} },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/orderRef": {
      orderReference: (row, fallback) => row.order_no || row.production_no || fallback,
      rawOrderReference: (row, fallback) => row.order_no || row.production_no || fallback,
    },
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

const referenced = createHarness([bundle()]);
let referencedTree = referenced.render();
assert.equal(referenced.requests.filter((key) => key === departmentKey).length, 1);
assert.match(textContent(referencedTree), /page\.cuttingInventory\.toPrinting/);
const groupButton = find(referencedTree, (node) => node.type === "button" && node.props["aria-expanded"] === false);
assert.ok(groupButton, "the real bundle group control must render");
groupButton.props.onClick();
referenced.requests.length = 0;
referencedTree = referenced.render();
assert.equal(referenced.requests.filter((key) => key === departmentKey).length, 1);
assert.match(textContent(referencedTree), /B-31/);
assert.match(textContent(referencedTree), /dash\.printing/);

const withoutReference = createHarness([bundle({ next_department_id: null, status: "sent_to_sewing" })]);
const withoutReferenceTree = withoutReference.render();
assert.equal(withoutReference.requests.filter((key) => key === departmentKey).length, 0);
assert.match(textContent(withoutReferenceTree), /page\.cuttingInventory\.toSewing/);

const denied = createHarness([], { denied: true });
const deniedTree = denied.render();
assert.equal(denied.requests.filter((key) => key === departmentKey).length, 0);
assert.match(textContent(deniedTree), /page\.cuttingInventory\.empty/);
assert.doesNotMatch(textContent(deniedTree), /B-31|dash\.printing/);

console.log("Cutting inventory departments: unreferenced/denied key 1 -> 0; referenced bundles remain exactly 1 with destination rendering intact.");
