import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/inventory/receive/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const state = [];
let index = 0;
let itemSize = 1;
let itemKeys = [];
let infiniteCall = 0;
let effectCursor = 0;
const effectDeps = [];
global.window = { setTimeout: callback => { callback(); return 1; }, clearTimeout() {} };
const hooks = {
  ...React,
  useMemo(factory) { return factory(); },
  useEffect(effect, deps) {
    const slot = effectCursor++;
    if (!deps || !effectDeps[slot] || deps.some((value, index) => value !== effectDeps[slot][index])) effect();
    effectDeps[slot] = deps;
  },
  useState(initial) {
    const slot = index++;
    if (!(slot in state)) state[slot] = typeof initial === "function" ? initial() : initial;
    return [state[slot], value => { state[slot] = typeof value === "function" ? value(state[slot]) : value; }];
  },
};
const itemRows = page => Array.from({ length: page === 10 ? 1 : 50 }, (_, row) => {
  const id = page * 50 + row + 1;
  return { id, sku: `SKU-${id}`, name: id === 501 ? "Late receiving material" : `Item ${id}`, unit: id === 501 ? "m" : "kg" };
});
const component = () => null;
const posts = [];
const exports = {};
const modules = {
  react: hooks,
  "react/jsx-runtime": jsxRuntime,
  "next/navigation": { useSearchParams: () => new URLSearchParams("group=materials") },
  swr: { default: () => ({ data: undefined, mutate: async () => {} }) },
  "swr/infinite": { default: getKey => {
    const call = infiniteCall++;
    if (call !== 0) return { data: [], size: 1, setSize() {}, mutate: async () => {}, isLoading: false, isValidating: false };
    const pages = [];
    itemKeys = [];
    for (let page = 0; page < itemSize; page++) {
      const key = getKey(page, pages.at(-1) || null);
      itemKeys.push(key);
      if (!key) break;
      const searching = key.includes("q=UNRELATED");
      pages.push({ rows: searching ? [{ id: 900, sku: "UNRELATED", name: "Different item", unit: "pcs" }] : itemRows(page), total: searching ? 1 : 501 });
    }
    return { data: itemKeys[0] ? pages : undefined, size: itemSize, setSize(next) { itemSize = next; }, mutate: async () => {}, isLoading: false, isValidating: false };
  } },
  "@/lib/api": { api: { post: async path => { posts.push(path); return {}; }, upload: async () => ({}) }, fetcher() {} },
  "@/lib/useModelOptions": { modelOptionsByIdsFetcher() {}, modelOptionsByIdsKey: () => null },
  "@/components/MaterialRollWeightFields": { default: component, rollWeightsTotal: () => 0, validRollWeights: () => true },
  "@/components/PageHeader": { default: component },
  "@/components/PaginationControls": { default: component },
  "@/components/SearchableSelect": { default: component },
  "@/components/SupplierAsyncSelect": { default: component },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
  "@/lib/orderRef": { formatOrderReference: value => value, orderReference: row => row.order_no || row.production_no || "" },
  "@/lib/modelImages": { imagePreviewHref: value => value, storageThumbnailUrl: value => value },
  "@/lib/materialColors": { MATERIAL_COLOR_OPTIONS: [], materialColorLabelKey: value => value },
  "@/lib/materialRollWeights": { divideBatchQuantityByRollCount: () => 0 },
};
new Function("exports", "require", output)(exports, name => {
  assert.ok(name in modules, `Unexpected dependency: ${name}`);
  return modules[name];
});

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  for (const child of Array.isArray(node.props?.children) ? node.props.children : [node.props?.children]) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}
function receiveForm() {
  index = 0;
  infiniteCall = 0;
  effectCursor = 0;
  return find(exports.default(), node => node.props?.onAsyncItemOpenChange && node.props?.form && node.props?.submitLabel === "btn.receive").props;
}

let props = receiveForm();
assert.deepEqual(itemKeys, [null], "closed receive picker must not request the catalog");
await props.onSubmit({ preventDefault() {} });
props = receiveForm();
assert.equal(props.message, "page.modelDetail.selectItem", "an item must be chosen before receiving");
assert.deepEqual(posts, [], "missing item must not reach the write API");
props.onAsyncItemOpenChange(true);
props = receiveForm();
assert.equal(itemKeys[0], "/api/inventory/items?group=materials&page=1&page_size=50&include_total=true&q=");
for (let page = 2; page <= 11; page++) {
  props.onAsyncItemLoadMore();
  props = receiveForm();
  assert.equal(itemKeys[page - 1], `/api/inventory/items?group=materials&page=${page}&page_size=50&include_total=true&q=`);
}
assert.equal(props.asyncItemHasMore, false);
assert.ok(props.asyncItemOptions.some(option => option.value === 501));
props.onAsyncItemChange(501);
props = receiveForm();
assert.equal(props.form.item_id, 501);
assert.equal(props.form.unit, "m", "selected item metadata must update the receiving unit");
props.onAsyncItemSearchChange("UNRELATED");
receiveForm();
props = receiveForm();
assert.equal(itemKeys[0], "/api/inventory/items?group=materials&page=1&page_size=50&include_total=true&q=UNRELATED");
assert.ok(props.asyncItemOptions.some(option => option.value === 501), "selected item must survive a different search");
props.onAsyncItemOpenChange(false);
props = receiveForm();
assert.deepEqual(itemKeys, [null]);
assert.equal(props.form.item_id, 501);
console.log("Inventory Receive item picker reaches item 501, keeps unit and selection, and stays idle when closed.");
