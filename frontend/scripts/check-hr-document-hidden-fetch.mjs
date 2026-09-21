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
    if (key === "/api/hr/documents") return { data: [], error: undefined, isLoading: false, mutate: async () => {} };
    if (key === "/api/employees") return { data: [{ id: 17, full_name: "Synthetic Employee" }] };
    return { data: undefined };
  } },
  "@/lib/api": { api: { postForm: async () => ({}) }, fetcher() {} },
  "@/components/Modal": { default: ({ open, children }) => open ? React.createElement("section", null, children) : null },
  "@/components/hr/HrUi": {
    HrHeader: ({ actions }) => React.createElement("header", null, actions),
    LoadState: ({ children }) => React.createElement(React.Fragment, null, children),
    MetricGrid: () => null,
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
assert.deepEqual(keys, ["/api/hr/documents", null], "closed upload section must not fetch employees");
assert.ok(!renderToStaticMarkup(closed).includes("Synthetic Employee"));
const uploadButton = find(closed, node => node.type === "button" && node.props.children === "Upload document");
assert.ok(uploadButton, "actual Upload document action must render");
uploadButton.props.onClick();

keys.length = 0;
const opened = render();
assert.deepEqual(keys, ["/api/hr/documents", "/api/employees"], "opening upload must fetch employee options");
assert.ok(renderToStaticMarkup(opened).includes("Synthetic Employee"), "open upload must render fetched employee options");

console.log("HR documents: employee options fetch only after the upload section opens.");
