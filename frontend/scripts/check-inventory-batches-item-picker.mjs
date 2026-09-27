import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/inventory/batches/page.tsx", import.meta.url), "utf8");
const selectSource = fs.readFileSync(new URL("../src/components/SearchableSelect.tsx", import.meta.url), "utf8");
assert.match(selectSource, /onOpenChange\?\.\(open\)/, "picker must report when it opens and closes");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const state = [];
let index = 0;
let itemSize = 1;
let itemKeys = [];
global.window = { setTimeout: callback => { callback(); return 1; }, clearTimeout() {} };
const hooks = {
  ...React,
  useMemo(factory) { return factory(); },
  useEffect(effect) { effect(); },
  useState(initial) {
    const slot = index++;
    if (!(slot in state)) state[slot] = typeof initial === "function" ? initial() : initial;
    return [state[slot], value => { state[slot] = typeof value === "function" ? value(state[slot]) : value; }];
  },
};
const itemRows = page => Array.from({ length: page === 10 ? 1 : 50 }, (_, row) => {
  const id = page * 50 + row + 1;
  return { id, sku: `SKU-${id}`, name: id === 501 ? "Off-page item" : `Item ${id}` };
});
const SearchableSelect = () => null;
const exports = {};
new Function("exports", "require", output)(exports, name => ({
  react: hooks,
  "react/jsx-runtime": jsxRuntime,
  "next/link": { default: () => null },
  swr: { default: () => ({ data: { rows: [], total: 0 } }) },
  "swr/infinite": { default: getKey => {
    const pages = [];
    itemKeys = [];
    for (let page = 0; page < itemSize; page++) {
      const key = getKey(page, pages.at(-1) || null);
      itemKeys.push(key);
      if (!key) break;
      pages.push({ rows: itemRows(page), total: 501 });
    }
    return { data: itemKeys[0] ? pages : undefined, size: itemSize, setSize: next => { itemSize = next; }, isLoading: false, isValidating: false };
  } },
  "@/lib/orderRef": { formatOrderReference: value => value },
  "@/lib/api": { fetcher() {} },
  "@/components/PageHeader": { default: () => null },
  "@/components/PaginationControls": { default: () => null },
  "@/components/SearchableSelect": { default: SearchableSelect },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
})[name]);

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  for (const child of Array.isArray(node.props?.children) ? node.props.children : [node.props?.children]) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}
function picker() {
  index = 0;
  return find(exports.default(), node => node.type === SearchableSelect).props;
}

let props = picker();
assert.deepEqual(itemKeys, [null], "closed picker must not fetch item pages");
props.onOpenChange(true);
props = picker();
assert.deepEqual(itemKeys, ["/api/inventory/items?page=1&page_size=50&include_total=true&q="]);
assert.equal(props.options.length, 51);
assert.equal(props.hasMore, true);
for (let page = 2; page <= 11; page++) {
  props.onLoadMore();
  props = picker();
  assert.equal(itemKeys[page - 1], `/api/inventory/items?page=${page}&page_size=50&include_total=true&q=`);
}
assert.equal(props.hasMore, false);
const offPage = props.options.find(option => option.value === 501);
assert.ok(offPage, "off-page item must become selectable");
props.onChange(501, offPage);
props.onOpenChange(false);
props = picker();
assert.deepEqual(itemKeys, [null], "closing the picker must stop item requests");
assert.equal(props.value, 501);
assert.equal(props.options.find(option => option.value === 501)?.label, "Off-page item", "selection must survive closed pages");
console.log("Inventory Batches item picker reaches item 501, preserves selection, and stays idle when closed.");
