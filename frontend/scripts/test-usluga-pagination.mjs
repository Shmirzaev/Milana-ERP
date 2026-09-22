import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/usluga/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

const state = [];
let stateIndex = 0;
const swrCalls = [];
let setSizeCalls = [];
let swrSize = 1;
const orders = [
  { id: 1, order_no: "US-001", status: "planning", customer_name: "Alpha", customer_reference: null, model: null, model_id: 1, planned_quantity: 2, deadline: null, material_description: null, material_usage_kg: null, handed_over_at: null, ready_for_handover: false, work_orders: [] },
  { id: 2, order_no: "US-002", status: "ready_for_handover", customer_name: "Beta", customer_reference: null, model: null, model_id: 1, planned_quantity: 3, deadline: null, material_description: null, material_usage_kg: null, handed_over_at: null, ready_for_handover: true, work_orders: [] },
];

function useState(initial) {
  const index = stateIndex++;
  if (!(index in state)) state[index] = initial;
  return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
}
function useMemo(factory) { return factory(); }
function useEffect() {}
function jsx(type, props) { return { type, props: props || {} }; }
const react = { useState, useMemo, useEffect };
const noopComponent = () => null;
const icon = () => null;
const icons = Object.fromEntries(["ClipboardCheck", "ExternalLink", "PackageCheck", "Pencil", "Plus", "RefreshCw", "Scissors", "Shirt", "Trash2"].map(name => [name, icon]));
const statusPages = {
  "": [{ rows: [orders[0]], total: 2, page: 1, page_size: 100 }, { rows: [orders[1]], total: 2, page: 2, page_size: 100 }],
  ready_for_handover: [{ rows: [orders[1]], total: 1, page: 1, page_size: 100 }],
};
function useSWRInfinite(keyFactory) {
  swrCalls.push(keyFactory);
  const status = state[1] || "";
  const pages = statusPages[status] || [];
  return {
    data: pages.slice(0, swrSize), error: undefined, isLoading: false, isValidating: false,
    mutate: async () => {}, size: swrSize,
    setSize: async value => { setSizeCalls.push(value); swrSize = value; },
  };
}

const module = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "react") return react;
  if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
  if (name === "next/link") return { default: ({ children, ...props }) => jsx("a", { ...props, children }) };
  if (name === "swr") return { default: () => ({ data: undefined }) };
  if (name === "swr/infinite") return { default: useSWRInfinite };
  if (name === "lucide-react") return icons;
  if (name === "@/lib/api") return { api: { post: async () => ({}) }, fetcher: async () => ({}) };
  if (name === "@/lib/auth") return { can: () => true, useMe: () => ({ me: { id: 1 } }) };
  if (name === "@/lib/i18n") return { useT: () => ({ t: key => key }) };
  if (name === "@/lib/garmentSizes") return { GARMENT_SIZE_OPTIONS: [] };
  if (name === "@/lib/modelImages") return { storageThumbnailUrl: value => value };
  if (name === "@/lib/orderRef") return { formatOrderReference: (value, fallback = "-") => value == null ? fallback : String(value) };
  if (["@/components/Modal", "@/components/ModelAsyncSelect", "@/components/PageHeader", "@/components/VerticalModelPhoto"].includes(name)) return { default: noopComponent };
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);
const UslugaPage = module.exports.default;

function render() {
  stateIndex = 0;
  return UslugaPage();
}
function walk(node, predicate, found = []) {
  if (!node || typeof node !== "object") return found;
  if (predicate(node)) found.push(node);
  for (const child of Object.values(node.props || {})) {
    if (Array.isArray(child)) child.forEach(item => walk(item, predicate, found));
    else walk(child, predicate, found);
  }
  return found;
}
function containsText(value, text) {
  if (value === text) return true;
  if (Array.isArray(value)) return value.some(item => containsText(item, text));
  return Boolean(value && typeof value === "object" && containsText(value.props?.children, text));
}

let tree = render();
assert.equal(swrCalls.at(-1)(0), "/api/usluga/orders?page=1&page_size=100");
assert(containsText(tree, "US-001"), "first page renders its order row");
assert(!containsText(tree, "US-002"), "first page does not render unloaded orders");
const statusSelect = walk(tree, node => node.type === "select").at(-1);
assert(statusSelect, "status filter select is rendered");
statusSelect.props.onChange({ target: { value: "ready_for_handover" } });
tree = render();
assert.equal(swrCalls.at(-1)(0), "/api/usluga/orders?page=1&page_size=100&status=ready_for_handover");
assert(containsText(tree, "US-002"), "status-filtered page renders its matching order row");

// Return to the unfiltered view and invoke the actual rendered load-more handler.
statusSelect.props.onChange({ target: { value: "" } });
swrSize = 1;
tree = render();
const loadMore = walk(tree, node => node.type === "button" && containsText(node.props.children, "common.loadMore"))[0];
assert(loadMore, "load-more button is rendered while another page exists");
await loadMore.props.onClick();
assert.deepEqual(setSizeCalls, [2], "load-more invokes SWR pagination with the next page number");
stateIndex = 0;
tree = render();
assert(containsText(tree, "US-001") && containsText(tree, "US-002"), "second page is aggregated into the visible table");
console.log("PASS: Usluga component SWR key, server status filter, rendered load-more handler, and page aggregation pass.");
