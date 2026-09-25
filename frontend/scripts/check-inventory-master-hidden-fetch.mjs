import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/inventory/master-data/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const hookState = [];
let hookIndex = 0;
const keys = [];
let materialSize = 1;
let accessorySize = 1;
const materialRows = Array.from({ length: 50 }, (_, index) => ({ id: index + 1, name: index === 0 ? "Visible Material" : `Material ${index + 1}`, composition: [] }));
const hooks = {
  ...React,
  useMemo(factory) { return factory(); },
  useEffect(effect) { effect(); },
  useState(initial) {
    const index = hookIndex++;
    if (!(index in hookState)) hookState[index] = typeof initial === "function" ? initial() : initial;
    return [hookState[index], value => {
      hookState[index] = typeof value === "function" ? value(hookState[index]) : value;
    }];
  },
};

const exports = {};
new Function("exports", "require", output)(exports, name => ({
  react: hooks,
  "react/jsx-runtime": jsxRuntime,
  swr: { default: key => {
    keys.push(key);
    if (key === "/api/suppliers") return { data: [{ id: 3, name: "Deferred Supplier" }], mutate: async () => {} };
    return { data: undefined, mutate: async () => {} };
  } },
  "swr/infinite": { default: getKey => {
    const first = getKey(0, null);
    keys.push(first);
    const isMaterial = first?.includes("group=materials");
    const size = isMaterial ? materialSize : accessorySize;
    const pages = [];
    for (let index = 0; first && index < size; index++) {
      const key = getKey(index, index > 0 ? pages[index - 1] : null);
      if (!key) break;
      const rows = isMaterial ? index === 0 ? materialRows : [{ id: 51, name: "Material 51", composition: [] }]
        : [{ id: 2, name: "Deferred Accessory", composition: [] }];
      pages.push({ rows, total: isMaterial ? 51 : 1, page: index + 1, page_size: 50 });
    }
    return { data: pages, size, setSize(next) { if (isMaterial) materialSize = next; else accessorySize = next; }, mutate: async () => {} };
  } },
  "lucide-react": Object.fromEntries(["Edit3", "Plus", "Search", "Trash2", "X"].map(icon => [icon, () => null])),
  "@/lib/access": { isMaterialsOnly: () => false },
  "@/components/PageHeader": { default: () => null },
  "@/lib/api": { api: { post: async () => ({}), patch: async () => ({}), del: async () => ({}) }, fetcher() {} },
  "@/lib/auth": { can: () => true, useMe: () => ({ me: { id: 7 } }) },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
  "@/components/DialogProvider": { useDialogs: () => ({ ask: async () => true }) },
  "@/lib/materialComposition": {
    compositionTotal: () => 0,
    formatComposition: value => Array.isArray(value) ? "" : String(value || ""),
  },
})[name]);

function render() {
  hookIndex = 0;
  return exports.default();
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  const children = node.props?.children;
  for (const child of Array.isArray(children) ? children : [children]) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}

const materials = render();
assert.deepEqual(keys, [
  "/api/inventory/items?group=materials&page=1&page_size=50&include_total=true&master_data_search=true&q=",
  null,
  null,
], "hidden Accessories and Suppliers tabs must not fetch their directories");
const materialsHtml = renderToStaticMarkup(materials);
assert.ok(materialsHtml.includes("Visible Material"));
assert.ok(!materialsHtml.includes("Deferred Accessory"));
const loadMore = find(materials, node => node.type === "button" && String(node.props?.children).includes("common.loadMore"));
assert.ok(loadMore, "the material list should expose its next exact-total page");
loadMore.props.onClick();
keys.length = 0;
const expandedMaterials = render();
assert.ok(renderToStaticMarkup(expandedMaterials).includes("Material 51"));
const accessoriesTab = find(materials, node => node.type === "button" && node.props.children === "page.masterData.accessories");
assert.ok(accessoriesTab, "actual Accessories tab action must render");
accessoriesTab.props.onClick();

keys.length = 0;
const accessories = render();
assert.deepEqual(keys, [
  null,
  "/api/inventory/items?group=accessories&page=1&page_size=50&include_total=true&master_data_search=true&q=",
  null,
], "opening Accessories must fetch the same authorized item endpoint");
assert.ok(renderToStaticMarkup(accessories).includes("Deferred Accessory"));

const suppliersTab = find(accessories, node => node.type === "button" && node.props.children === "page.masterData.suppliers");
assert.ok(suppliersTab, "actual Suppliers tab action must render");
suppliersTab.props.onClick();

keys.length = 0;
const suppliers = render();
assert.deepEqual(keys, [
  null,
  null,
  "/api/suppliers",
], "opening Suppliers must fetch the same authorized supplier endpoint");
assert.ok(renderToStaticMarkup(suppliers).includes("Deferred Supplier"));

console.log("Inventory master data: accessory and supplier directories fetch only when their tabs open.");
