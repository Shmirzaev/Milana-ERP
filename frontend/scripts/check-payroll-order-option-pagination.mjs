import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/payroll/reports/order-qr-status/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const firstRows = Array.from({ length: 50 }, (_, index) => ({
  order_no: `SO-${String(index + 1).padStart(3, "0")}`,
  sales_order_nos: [`SO-${String(index + 1).padStart(3, "0")}`],
  production_nos: [],
  model_codes: [],
  label_count: 1,
}));
const secondRow = {
  order_no: "SO-051", sales_order_nos: ["SO-051"], production_nos: [], model_codes: [], label_count: 1,
};
const pages = [
  { rows: firstRows, total: 51, page: 1, page_size: 50, has_more: true },
  { rows: [secondRow], total: 51, page: 2, page_size: 50, has_more: false },
];
const iconExports = new Proxy({}, { get: () => function Icon() { return null; } });

function harness() {
  const hookState = [];
  let hookIndex = 0;
  let optionPageCount = 1;
  let lastFirstKey;
  const keys = [];
  const hooks = {
    ...React,
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
    "swr": { default: key => {
      keys.push(key);
      return { data: undefined, error: undefined, isLoading: false };
    } },
    "swr/infinite": { default: getKey => {
      const firstKey = getKey(0, null);
      if (firstKey !== lastFirstKey) {
        optionPageCount = 1;
        lastFirstKey = firstKey;
      }
      const visiblePages = [];
      for (let index = 0; index < optionPageCount; index += 1) {
        const previousPage = index ? visiblePages[index - 1] : null;
        const key = index ? getKey(index, previousPage) : firstKey;
        if (!key) break;
        keys.push(key);
        visiblePages.push(pages[index]);
      }
      return {
        data: visiblePages,
        error: undefined,
        isLoading: false,
        isValidating: false,
        size: optionPageCount,
        setSize: async value => {
          optionPageCount = typeof value === "function" ? value(optionPageCount) : value;
        },
      };
    } },
    "lucide-react": iconExports,
    "@/components/PageHeader": { default: "page-header" },
    "@/components/PaginationControls": { default: "pagination-controls" },
    "@/lib/api": { fetcher() {} },
    "@/lib/i18n": { useT: () => ({
      lang: "en",
      t: (key, values) => key === "common.showingRange"
        ? `Showing ${values.start}-${values.end} of ${values.total}`
        : key === "common.loadMore" ? "Load more" : key,
    }) },
    "@/lib/orderRef": { formatOrderReference: value => value },
  })[name]);
  return {
    keys,
    render() {
      hookIndex = 0;
      return exports.default();
    },
  };
}

function find(node, predicate) {
  if (!node || typeof node !== "object") return null;
  if (predicate(node)) return node;
  const children = Array.isArray(node.props?.children) ? node.props.children : [node.props?.children];
  for (const child of children) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}

const view = harness();
const first = view.render();
assert.match(view.keys[0], /page=1&page_size=50/);
assert.ok(renderToStaticMarkup(first).includes("SO-050"));
assert.ok(renderToStaticMarkup(first).includes("Showing 1-50 of 51"));
const more = find(first, node => node.type === "button" && node.props.children === "Load more");
assert.ok(more, "the option directory must expose Load more when another page exists");
await more.props.onClick();

view.keys.length = 0;
const expanded = view.render();
assert.deepEqual(view.keys.filter(key => typeof key === "string" && key.includes("order-qr-status/orders"))
  .map(key => new URL(key, "http://localhost").searchParams.get("page")), ["1", "2"]);
assert.ok(renderToStaticMarkup(expanded).includes("SO-051"));
assert.ok(renderToStaticMarkup(expanded).includes("Showing 1-51 of 51"));
assert.equal(find(expanded, node => node.type === "button" && node.props.children === "Load more"), null);

const input = find(expanded, node => node.type === "input" && node.props.list === "order-qr-options");
input.props.onChange({ target: { value: "SO 20%" } });
view.keys.length = 0;
view.render();
const searchedKey = view.keys.find(key => typeof key === "string" && key.includes("order-qr-status/orders"));
assert.equal(new URL(searchedKey, "http://localhost").searchParams.get("search"), "SO 20%");
assert.equal(new URL(searchedKey, "http://localhost").searchParams.get("page_size"), "50");

console.log("Payroll order options: exact totals display and 50-row Load more follows search pages.");
