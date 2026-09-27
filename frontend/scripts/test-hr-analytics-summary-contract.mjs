import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/hr/analytics/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const analytics = {
  total_headcount: 3,
  inactive_headcount: 1,
  retention_rate: 75,
  average_tenure_years: 2.4,
  average_salary: 1000.5,
  gender_distribution: { female: 2, male: 1 },
  age_distribution: { under_25: 1, "25_34": 2, "35_44": 0, "45_plus": 0 },
};
const requests = [];
const exports = {};

new Function("exports", "require", output)(exports, name => {
  if (name === "react/jsx-runtime") return jsxRuntime;
  if (name === "swr") return { __esModule: true, default: key => {
    requests.push(key);
    return { data: analytics, error: undefined, isLoading: false };
  } };
  if (name === "@/lib/api") return { fetcher() {} };
  if (name === "@/components/hr/HrUi") return {
    HrHeader: ({ title, subtitle }) => React.createElement("header", null, title, subtitle),
    LoadState: ({ children }) => React.createElement(React.Fragment, null, children),
    MetricGrid: ({ items }) => React.createElement("section", null, items.map(item => React.createElement("div", { key: item.label }, `${item.label}:${item.value}`))),
  };
  throw new Error(`Unexpected import: ${name}`);
});

const markup = renderToStaticMarkup(exports.default());
assert.deepEqual(requests, ["/api/hr/analytics"], "the page should request the compact, factory-scoped analytics projection");
assert.match(markup, /Total headcount:3/);
assert.match(markup, /Retention:75%/);
assert.match(markup, /Average tenure:2\.4 years/);
assert.match(markup, /Average salary:1,000\.5/);
assert.match(markup, /Gender distribution/);
assert.match(markup, /female[\s\S]*?2/);
assert.match(markup, /Age distribution/);
assert.doesNotMatch(source, /\/api\/hr\/employees|useSWRInfinite|\.map\(\(employee\)/, "analytics must not load or render an employee directory graph");

console.log("PASS: HR analytics keeps exact aggregate KPIs and distributions on the compact analytics endpoint.");
