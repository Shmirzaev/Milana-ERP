import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/purchasing/page.tsx", import.meta.url), "utf8");
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
  useEffect(effect) { effect(); },
  useMemo(factory) { return factory(); },
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
  "next/link": { default: ({ children, ...props }) => React.createElement("a", props, children) },
  swr: { default: key => {
    keys.push(key);
    if (key === "/api/purchasing/requests") return { data: [], mutate: async () => {} };
    if (key === "/api/purchasing/orders") return { data: [], mutate: async () => {} };
    if (key === "/api/inventory/items?group=materials&page_size=500") {
      return { data: [{ id: 1, sku: "FAB-1", name: "Deferred Fabric", unit: "kg" }] };
    }
    if (key === "/api/inventory/items?group=accessories&page_size=500") {
      return { data: [{ id: 2, sku: "ACC-1", name: "Deferred Button", unit: "pcs" }] };
    }
    if (key === "/api/suppliers") return { data: [{ id: 3, name: "Visible Supplier" }] };
    return { data: undefined, mutate: async () => {} };
  } },
  "lucide-react": Object.fromEntries([
    "Check", "ChevronDown", "Folder", "ImagePlus", "PackageCheck", "Plus", "ShoppingCart", "X",
  ].map(icon => [icon, () => null])),
  "@/components/PageHeader": { default: ({ actions }) => React.createElement("header", null, actions) },
  "@/components/StagePipeline": { statusLabel: value => value },
  "@/lib/api": {
    api: { post: async () => ({}), postForm: async () => ({}), del: async () => ({}) },
    fetcher() {},
  },
  "@/lib/auth": {
    can: (me, permission) => Boolean(me?.permissions.includes(permission)),
    useMe: () => ({ me: { id: 7, permissions: ["purchasing.view", "purchasing.request"] } }),
  },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
  "@/lib/imageUpload": { prepareModelImageUpload: async file => file },
  "@/lib/orderRef": { formatOrderReference: value => String(value || "") },
})[name]);

function render() {
  hookIndex = 0;
  return exports.default();
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  const nested = [node.props?.children, node.props?.actions].flatMap(value => Array.isArray(value) ? value : [value]);
  for (const child of nested) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}

const closed = render();
assert.deepEqual(keys, [
  "/api/purchasing/requests",
  "/api/purchasing/orders",
  null,
  null,
  "/api/suppliers",
], "closed request form must not fetch either 500-item directory");
const closedHtml = renderToStaticMarkup(closed);
assert.ok(closedHtml.includes("Visible Supplier") === false);
assert.ok(!closedHtml.includes("Deferred Fabric"));
assert.ok(!closedHtml.includes("Deferred Button"));

const openButton = find(closed, node => node.type === "button" && node.props.children?.[1] === "page.purchasing.createSample");
assert.ok(openButton, "actual Create request action must render");
openButton.props.onClick();

keys.length = 0;
const opened = render();
assert.deepEqual(keys, [
  "/api/purchasing/requests",
  "/api/purchasing/orders",
  "/api/inventory/items?group=materials&page_size=500",
  "/api/inventory/items?group=accessories&page_size=500",
  "/api/suppliers",
], "opening the request form must fetch the same authorized directories");
const openedHtml = renderToStaticMarkup(opened);
assert.ok(openedHtml.includes("Deferred Fabric"));
assert.ok(openedHtml.includes("Deferred Button"));
assert.ok(openedHtml.includes("Visible Supplier"));

console.log("Purchasing: item directories fetch only when Create request opens.");
