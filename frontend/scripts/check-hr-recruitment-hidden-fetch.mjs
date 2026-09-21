import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/hr/recruitment/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const candidate = {
  id: 31, position_id: 4, department_id: 8, full_name: "Test Candidate",
  first_name: "Candidate", last_name: "Test", middle_name: null, date_of_birth: null,
  gender: null, nationality: null, country: null, region: null, district: null,
  address: null, passport_number: null, passport_issued_by: null, passport_issue_date: null,
  passport_expiry_date: null, pinfl: null, phone: null, email: null, source: null,
  stage: "applied", applied_on: "2026-09-21", interview_at: null, notes: null,
};

function harness() {
  const hookState = [];
  let hookIndex = 0;
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
    swr: { default: key => {
      keys.push(key);
      if (key === "/api/hr/recruitment") return { data: [candidate], error: undefined, isLoading: false, mutate: async () => {} };
      if (key === "/api/hr/positions") return { data: [{ id: 4, name: "Pattern Maker" }] };
      if (key === "/api/departments") return { data: [{ id: 8, name: "Synthetic Department" }] };
      return { data: undefined };
    } },
    "@/components/Modal": { default: ({ open, children }) => open ? React.createElement("section", null, children) : null },
    "@/components/hr/HrUi": {
      HrHeader: ({ actions }) => React.createElement("header", null, actions),
      LoadState: ({ children }) => React.createElement(React.Fragment, null, children),
      MetricGrid: () => null,
      useHrT: () => value => value,
    },
    "@/lib/api": { api: { post: async () => ({}), patch: async () => ({}) }, fetcher() {} },
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
  const nested = [node.props?.children, node.props?.actions].flatMap(value => Array.isArray(value) ? value : [value]);
  for (const child of nested) {
    const match = find(child, predicate);
    if (match) return match;
  }
  return null;
}

for (const actionLabel of ["Add candidate", "View / edit"]) {
  const view = harness();
  const closed = view.render();
  assert.deepEqual(view.keys, ["/api/hr/recruitment", "/api/hr/positions", null],
    "closed candidate modal must not fetch departments");
  assert.ok(!renderToStaticMarkup(closed).includes("Synthetic Department"));
  const action = find(closed, node => node.type === "button" && node.props.children === actionLabel);
  assert.ok(action, `actual ${actionLabel} action must render`);
  action.props.onClick();

  view.keys.length = 0;
  const opened = view.render();
  assert.deepEqual(view.keys, ["/api/hr/recruitment", "/api/hr/positions", "/api/departments"],
    `${actionLabel} must fetch departments while preserving visible positions`);
  assert.ok(renderToStaticMarkup(opened).includes("Synthetic Department"),
    `${actionLabel} must render fetched department options`);
}

console.log("HR recruitment: department options fetch only when create or edit opens.");
