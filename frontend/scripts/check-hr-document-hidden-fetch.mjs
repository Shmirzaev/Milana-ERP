import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/hr/documents/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const hookState = [];
let hookIndex = 0;
const keys = [];
let documentPages = 1;
const hooks = {
  ...React,
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
    if (key === "/api/employees") return { data: [{ id: 17, full_name: "Synthetic Employee" }] };
    return { data: undefined };
  } },
  "swr/infinite": { default: () => {
    keys.push(`/api/hr/documents?page=${documentPages}&page_size=100`);
    const pages = Array.from({ length: documentPages }, (_, index) => ({
      rows: [{ id: index + 1, employee_id: 17, employee_name: "Synthetic Employee", category: "other", title: `Document ${index + 1}`, original_name: "doc.pdf", size_bytes: 1024, expires_on: null, created_at: "2026-01-01T00:00:00Z", download_url: `/download/${index + 1}` }],
      total: 2, page: index + 1, page_size: 100, has_more: index === 0, metrics: { employee_folders: 1, archive_size_bytes: 2097152, expiring_in_30_days: 0 },
    }));
    return { data: pages, error: undefined, isLoading: false, mutate: async () => {}, setSize: async value => { documentPages = typeof value === "function" ? value(documentPages) : value; } };
  } },
  "@/lib/api": { api: { postForm: async () => ({}) }, fetcher() {} },
  "@/components/Modal": { default: ({ open, children }) => open ? React.createElement("section", null, children) : null },
  "@/components/hr/HrUi": {
    HrHeader: ({ actions }) => React.createElement("header", null, actions),
    LoadState: ({ children }) => React.createElement(React.Fragment, null, children),
    MetricGrid: ({ items }) => React.createElement("metrics", null, items.map(item => `${item.label}:${item.value}`).join("|")),
  },
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
assert.deepEqual(keys, ["/api/hr/documents?page=1&page_size=100", null], "closed upload section must not fetch employees");
const uploadButton = find(closed, node => node.type === "button" && node.props.children === "Upload document");
assert.ok(uploadButton, "actual Upload document action must render");
uploadButton.props.onClick();

keys.length = 0;
const opened = render();
assert.deepEqual(keys, ["/api/hr/documents?page=1&page_size=100", "/api/employees"], "opening upload must fetch employee options");
assert.ok(renderToStaticMarkup(opened).includes("Synthetic Employee"), "open upload must render fetched employee options");

const loadMore = find(opened, node => node.type === "button" && node.props.children === "Load more");
assert.ok(loadMore, "first page must expose load more");
await loadMore.props.onClick();
const paged = render();
const pagedMarkup = renderToStaticMarkup(paged);
assert.match(pagedMarkup, /Document 1/);
assert.match(pagedMarkup, /Document 2/);
assert.match(pagedMarkup, /Documents:2/);
assert.match(pagedMarkup, /Employee folders:1/);
assert.match(pagedMarkup, /Archive size:2\.0 MB/, "archive metrics must come from server metadata");

console.log("HR documents: employee options fetch only after the upload section opens.");
