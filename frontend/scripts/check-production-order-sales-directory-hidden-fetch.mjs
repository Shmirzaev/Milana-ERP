import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const salesDirectoryKey = "/api/sales-orders?page=1&page_size=50&include_total=true&q=";
const pageContextKey = "/api/production-orders/12/page-context";
const source = fs.readFileSync(new URL("../src/app/(app)/production-orders/[id]/page.tsx", import.meta.url), "utf8");
assert.match(
  source,
  /useSWRInfinite<SalesOrderOptionPage>/,
  "the sales-order picker must request bounded pages",
);
assert.match(source, /`\/api\/production-orders\/\$\{id\}\/page-context`/);
assert.doesNotMatch(source, /`\/api\/models\/\$\{po\.model_id\}`/);
assert.match(
  source,
  /pageContext \? \{ \.\.\.pageContext, production_order: updated \} : undefined/,
  "optimistic size updates must preserve the page-context envelope",
);
assert.match(
  source,
  /\{summaryEditing \? \([\s\S]*?salesOrders\.map/,
  "the sales-order directory must remain scoped to the active summary editor",
);
assert.match(
  source,
  /const flowUtilKey = editing\?\.operation === "sewing" \|\| openAssignments !== null[\s\S]*?"\/api\/sewing-flows\/utilization-snapshot"[\s\S]*?: null;/,
  "flow utilization must depend on an active sewing editor or assignment panel",
);
assert.match(
  source,
  /useSWR<any\[\]>\(canPlan && editing \? "\/api\/users" : null, fetcher\)/,
  "the user directory must depend on the authorized work-order editor",
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
  let optionPageCount = 1;

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
    const data = key === pageContextKey
      ? { production_order: {
          id: 12,
          production_no: "PO-12",
          sales_order_id: 21,
          model_id: 4,
          model_code: "MODEL-4",
          model_name: "Model 4",
          status: "new",
          source_type: "standard",
          planned_quantity: 100,
          work_orders: [{
            id: 44,
            operation: "sewing",
            status: "new",
            planned_input_qty: 100,
            planned_output_qty: 100,
            actual_input_qty: 0,
            actual_output_qty: 0,
            failed_qty: 0,
            sewing_flow_id: null,
          }],
          batches: [],
          items: [],
        }, model: { id: 4, code: "MODEL-4", name: "Model 4" } }
      : key === "/api/production-orders/12/material-reservation-status"
        ? undefined
        : key === "/api/sewing-flows"
          ? []
          : key === "/api/sewing-flows/utilization-snapshot"
            ? []
            : key === "/api/users"
              ? []
              : undefined;
    return { data, error: undefined, isLoading: false, mutate() {} };
  }

  function useSWRInfinite(getKey) {
    const pages = [];
    let previous = null;
    for (let index = 0; index < optionPageCount; index++) {
      const key = getKey(index, previous);
      requests.push(key);
      if (!key) break;
      const page = key.includes("&q=Client%20B")
        ? { rows: [], total: 0 }
        : index === 0
          ? { rows: [{ id: 21, order_no: "SO-21", customer_name: "Client A" }], total: 51 }
          : { rows: [{ id: 22, order_no: "SO-22", customer_name: "Client B" }], total: 51 };
      pages.push(page);
      previous = page;
    }
    return { data: pages, size: optionPageCount, setSize(next) { optionPageCount = next; dirty = true; } };
  }

  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: { useState },
    "next/navigation": { useParams: () => ({ id: "12" }) },
    swr: { default: useSWR },
    "swr/infinite": { default: useSWRInfinite },
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
assert.equal(closed.requests.filter((key) => key === pageContextKey).length, 1);
assert.equal(closed.requests.filter((key) => key === "/api/production-orders/12").length, 0);
assert.equal(closed.requests.filter((key) => key === "/api/models/4").length, 0);
assert.equal(closed.requests.filter((key) => key === salesDirectoryKey).length, 0);
assert.equal(closed.requests.filter((key) => key === "/api/sewing-flows/utilization-snapshot").length, 0);
assert.equal(closed.requests.filter((key) => key === "/api/users").length, 0);
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
const loadMore = find(open.tree, (node) => node.type === "button" && textContent(node.props?.children).includes("common.loadMore"));
assert.ok(loadMore, "the picker must expose the next exact-total page");
loadMore.props.onClick();
const expanded = authorized.render();
assert.ok(expanded.requests.includes("/api/sales-orders?page=2&page_size=50&include_total=true&q="));
assert.match(textContent(expanded.tree), /Client B/);
const selected = find(expanded.tree, (node) => node.type === "select" && node.props?.value === "21");
assert.ok(selected);
selected.props.onChange({ target: { value: "22" } });
const selectedTree = authorized.render();
const search = find(selectedTree.tree, (node) => node.type === "input" && node.props?.["aria-label"] === "common.search");
assert.ok(search);
search.props.onChange({ target: { value: "Client B" } });
const filtered = authorized.render();
assert.ok(filtered.requests.includes("/api/sales-orders?page=1&page_size=50&include_total=true&q=Client%20B"));
assert.match(textContent(filtered.tree), /Client B/, "selected off-page sales order must remain visible");

const assignmentEditor = createHarness(true);
const editorClosed = assignmentEditor.render();
const assignButton = find(editorClosed.tree, (node) => node.type === "button" && node.props?.children === "btn.assign");
assert.ok(assignButton, "the authorized sewing assignment action must render");
assignButton.props.onClick();
const editorOpen = assignmentEditor.render();
assert.equal(editorOpen.requests.filter((key) => key === "/api/sewing-flows/utilization-snapshot").length, 1);
assert.equal(editorOpen.requests.filter((key) => key === "/api/users").length, 1);

const splitPanel = createHarness(true);
const splitClosed = splitPanel.render();
const splitButton = find(splitClosed.tree, (node) => node.type === "button" && node.props?.children === "btn.split");
assert.ok(splitButton, "the sewing split action must render");
splitButton.props.onClick();
const splitOpen = splitPanel.render();
assert.equal(splitOpen.requests.filter((key) => key === "/api/sewing-flows/utilization-snapshot").length, 1);
assert.equal(splitOpen.requests.filter((key) => key === "/api/users").length, 0);

const denied = createHarness(false).render();
assert.equal(denied.requests.filter((key) => key === salesDirectoryKey).length, 0);
assert.equal(denied.requests.filter((key) => key === "/api/sewing-flows/utilization-snapshot").length, 0);
assert.equal(denied.requests.filter((key) => key === "/api/users").length, 0);
assert.equal(
  find(denied.tree, (node) => node.type === "button" && node.props?.children === "btn.edit"),
  null,
  "unauthorized users must retain no summary edit action",
);

console.log("Production-order directories: sales, utilization, and users stay dormant until their actual editors open.");
