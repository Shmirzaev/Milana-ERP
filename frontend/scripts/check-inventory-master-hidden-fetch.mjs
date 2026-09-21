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
    if (key === "/api/inventory/items?group=materials&page_size=500") return { data: [{ id: 1, name: "Visible Material", composition: [] }], mutate: async () => {} };
    if (key === "/api/inventory/items?group=accessories&page_size=500") return { data: [{ id: 2, name: "Deferred Accessory", composition: [] }], mutate: async () => {} };
    if (key === "/api/suppliers") return { data: [], mutate: async () => {} };
    return { data: undefined, mutate: async () => {} };
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
  "/api/inventory/items?group=materials&page_size=500",
  null,
  "/api/suppliers",
], "hidden Accessories tab must not fetch its item directory");
const materialsHtml = renderToStaticMarkup(materials);
assert.ok(materialsHtml.includes("Visible Material"));
assert.ok(!materialsHtml.includes("Deferred Accessory"));
const accessoriesTab = find(materials, node => node.type === "button" && node.props.children === "page.masterData.accessories");
assert.ok(accessoriesTab, "actual Accessories tab action must render");
accessoriesTab.props.onClick();

keys.length = 0;
const accessories = render();
assert.deepEqual(keys, [
  "/api/inventory/items?group=materials&page_size=500",
  "/api/inventory/items?group=accessories&page_size=500",
  "/api/suppliers",
], "opening Accessories must fetch the same authorized item endpoint");
assert.ok(renderToStaticMarkup(accessories).includes("Deferred Accessory"));

console.log("Inventory master data: accessory items fetch only when the Accessories tab opens.");
