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
const olderCandidate = { ...candidate, id: 30, full_name: "Older Candidate", stage: "interview" };

function harness() {
  const hookState = [];
  let hookIndex = 0;
  let candidatePageCount = 1;
  const keys = [];
  const hooks = {
    ...React,
    useDeferredValue(value) { return value; },
    useMemo(factory) { return factory(); },
    useState(initial) {
      const index = hookIndex++;
      if (!(index in hookState)) hookState[index] = typeof initial === "function" ? initial() : initial;
      return [hookState[index], value => {
        hookState[index] = typeof value === "function" ? value(hookState[index]) : value;
      }];
    },
  };
  const candidatePages = [
    { rows: [candidate], total: 2, page: 1, page_size: 100, has_more: true, stage_counts: { applied: 1, interview: 1 } },
    { rows: [olderCandidate], total: 2, page: 2, page_size: 100, has_more: false, stage_counts: { applied: 1, interview: 1 } },
  ];
  const exports = {};
  new Function("exports", "require", output)(exports, name => ({
    react: hooks,
    "react/jsx-runtime": jsxRuntime,
    "swr/infinite": { default: getKey => {
      const pages = candidatePages.slice(0, candidatePageCount);
      pages.forEach((page, index) => keys.push(getKey(index, index > 0 ? pages[index - 1] : null)));
      return {
        data: pages,
        error: undefined,
        isLoading: false,
        isValidating: false,
        mutate: async () => {},
        setSize: async value => {
          candidatePageCount = typeof value === "function" ? value(candidatePageCount) : value;
        },
      };
    } },
    swr: { default: key => {
      keys.push(key);
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
  assert.deepEqual(view.keys, ["/api/hr/recruitment?page=1&page_size=100", "/api/hr/positions", null],
    "closed candidate modal must not fetch departments");
  assert.ok(!renderToStaticMarkup(closed).includes("Synthetic Department"));
  assert.ok(renderToStaticMarkup(closed).includes("Test Candidate"));
  assert.ok(!renderToStaticMarkup(closed).includes("Older Candidate"));
  const loadMore = find(closed, node => node.type === "button" && node.props.children === "Load more");
  assert.ok(loadMore, "first candidate page must expose load more");
  await loadMore.props.onClick();

  view.keys.length = 0;
  const expanded = view.render();
  assert.deepEqual(view.keys, [
    "/api/hr/recruitment?page=1&page_size=100",
    "/api/hr/recruitment?page=2&page_size=100",
    "/api/hr/positions",
    null,
  ], "load more must retain page one and request the next bounded candidate page");
  const expandedMarkup = renderToStaticMarkup(expanded);
  assert.ok(expandedMarkup.includes("Test Candidate") && expandedMarkup.includes("Older Candidate"));
  assert.equal(find(expanded, node => node.type === "button" && node.props.children === "Load more"), null);

  const action = find(expanded, node => node.type === "button" && node.props.children === actionLabel);
  assert.ok(action, `actual ${actionLabel} action must render`);
  action.props.onClick();

  view.keys.length = 0;
  const opened = view.render();
  assert.deepEqual(view.keys, [
    "/api/hr/recruitment?page=1&page_size=100",
    "/api/hr/recruitment?page=2&page_size=100",
    "/api/hr/positions",
    "/api/departments",
  ],
    `${actionLabel} must fetch departments while preserving visible positions`);
  assert.ok(renderToStaticMarkup(opened).includes("Synthetic Department"),
    `${actionLabel} must render fetched department options`);
}

console.log("HR recruitment: bounded pages aggregate through load more and department options stay deferred.");
