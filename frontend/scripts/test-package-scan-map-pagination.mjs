import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/packages/scan/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

const scanned = { id: 9, package_no: "SCAN-9", model_id: 7, model_code: "M7", status: "received_in_storage" };
let stateIndex = 0;
let size = 1;
const requestedKeys = [];
const pages = [
  { rows: [{ id: 1, package_no: "PAGE-ONE", storage_cell: "A-01", storage_shelf: "1", total_quantity: 1, status: "packed" }], total: 2, has_more: true },
  { rows: [{ id: 2, package_no: "PAGE-TWO", storage_cell: "A-02", storage_shelf: "1", total_quantity: 2, status: "packed" }], total: 2, has_more: false },
];
function useState(initial) {
  const index = stateIndex++;
  return [index === 2 ? [scanned] : initial, () => {}];
}
function useSWR(key) {
  assert.equal(key, "/api/packages/storage-map/summary");
  return { data: { summary: { cells_occupied: 1, cells_total: 2, packages_on_map: 2 }, cells: [] }, mutate: async () => {} };
}
function useSWRInfinite(keyFactory) {
  requestedKeys.push(keyFactory(0, null), keyFactory(1, pages[0]), keyFactory(2, pages[1]));
  return { data: pages.slice(0, size), size, setSize: async next => { size = next; }, mutate: async () => {}, isValidating: false };
}
function jsx(type, props) { return { type, props: props || {} }; }
const noop = () => null;
const module = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "react") return { useState, useRef: () => ({ current: null }), useMemo: callback => callback() };
  if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
  if (name === "swr") return { default: useSWR };
  if (name === "swr/infinite") return { default: useSWRInfinite };
  if (name === "lucide-react") return { CheckSquare: noop, MapPin: noop, PackageCheck: noop, Trash2: noop };
  if (name === "@/lib/api") return { api: {}, fetcher: async () => ({}) };
  if (name === "@/lib/orderRef") return { formatOrderReference: value => String(value) };
  if (name === "@/lib/i18n") return { useT: () => ({ lang: "en", t: key => key }) };
  if (name === "@/lib/auth") return { can: () => true, useMe: () => ({ me: {} }) };
  if (name === "@/lib/modelImages") return { storageThumbnailUrl: () => "" };
  if (name === "@/components/StagePipeline") return { statusLabel: value => value };
  if (name === "@/lib/packageWorkflow") return { packageWorkflowCopy: { en: {} } };
  if (name.startsWith("@/components/")) return { default: noop };
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);

function walk(node, predicate, found = []) {
  if (!node || typeof node !== "object") return found;
  if (node.props && predicate(node)) found.push(node);
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
function render() { stateIndex = 0; return module.exports.default(); }

let tree = render();
assert.deepEqual(requestedKeys.slice(0, 3), [
  "/api/packages/storage-map/models/7?page=1&page_size=50",
  "/api/packages/storage-map/models/7?page=2&page_size=50",
  null,
]);
assert.equal(walk(tree, node => containsText(node.props.children, "PAGE-ONE")).length > 0, true);
assert.equal(walk(tree, node => containsText(node.props.children, "PAGE-TWO")).length, 0);
const loadMore = walk(tree, node => node.type === "button" && containsText(node.props.children, "common.loadMore"));
assert.equal(loadMore.length, 1);
await loadMore[0].props.onClick();
tree = render();
assert.equal(walk(tree, node => containsText(node.props.children, "PAGE-TWO")).length > 0, true);
assert.equal(walk(tree, node => node.type === "button" && containsText(node.props.children, "common.loadMore")).length, 0);
console.log("PASS: package scan map loads the selected model by bounded pages and stops at the end.");
