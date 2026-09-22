import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/hr/calendar/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const hookState = [];
let hookIndex = 0;
let calendarPages = 1;
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
  "swr/infinite": { default: getKey => {
    keys.push(getKey(calendarPages - 1));
    const pages = Array.from({ length: calendarPages }, (_, index) => ({
      rows: [{ id: index + 1, employee_id: null, event_type: index ? "training" : "contract_expiry", title: `Calendar event ${index + 1}`, starts_at: `2026-10-0${index + 1}T09:00:00Z`, ends_at: null, notes: null, status: "scheduled" }],
      total: 2,
      page: index + 1,
      page_size: 100,
      has_more: index === 0,
      metrics: { upcoming: 7, contracts_expiring: 3, probation_ending: 2, training: 2 },
    }));
    return { data: pages, error: undefined, isLoading: false, mutate: async () => {}, setSize: async value => { calendarPages = typeof value === "function" ? value(calendarPages) : value; } };
  } },
  "@/lib/api": { api: { post: async () => ({}) }, fetcher() {} },
  "@/lib/useHrCalendarEmployees": { useHrCalendarEmployees: () => ({ data: [] }) },
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

const first = render();
assert.deepEqual(keys, ["/api/hr/calendar?page=1&page_size=100"]);
const firstMarkup = renderToStaticMarkup(first);
assert.match(firstMarkup, /Calendar event 1/);
assert.match(firstMarkup, /Upcoming:7/);
assert.match(firstMarkup, /Contracts expiring:3/);
const loadMore = find(first, node => node.type === "button" && node.props.children === "Load more");
assert.ok(loadMore, "first page must expose load more");
await loadMore.props.onClick();

keys.length = 0;
const second = render();
assert.deepEqual(keys, ["/api/hr/calendar?page=2&page_size=100"]);
const secondMarkup = renderToStaticMarkup(second);
assert.match(secondMarkup, /Calendar event 1/);
assert.match(secondMarkup, /Calendar event 2/);
assert.equal(find(second, node => node.type === "button" && node.props.children === "Load more"), null);

console.log("PASS: HR calendar uses server metrics and aggregates paginated events through load more.");
