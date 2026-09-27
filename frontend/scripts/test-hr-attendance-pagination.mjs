import assert from "node:assert/strict";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const ts = await import("typescript").catch(() => null);

const source = fs.readFileSync(new URL("../src/app/(app)/hr/attendance/page.tsx", import.meta.url), "utf8");
assert.match(source, /useSWRInfinite<AttendancePage>/, "attendance must fetch pages instead of the legacy all-rows response");
assert.match(source, /page_size: String\(PAGE_SIZE\)/, "each API request must carry the bounded page size");

const output = ts?.default?.transpileModule ? ts.default.transpileModule(source, {
  compilerOptions: { jsx: ts.default.JsxEmit.React, module: ts.default.ModuleKind.CommonJS, target: ts.default.ScriptTarget.ES2020 },
}).outputText : null;
const keys = [];
let hookState = [];
let hookIndex = 0;
let pageCount = 1;

function useState(initial) {
  const index = hookIndex++;
  if (!(index in hookState)) hookState[index] = typeof initial === "function" ? initial() : initial;
  return [hookState[index], value => { hookState[index] = typeof value === "function" ? value(hookState[index]) : value; }];
}

function useSWRInfinite(getKey) {
  const pages = [];
  let previousPage;
  for (let index = 0; index < pageCount; index += 1) {
    const key = getKey(index, previousPage);
    if (!key) break;
    keys.push(key);
    const page = index === 0
      ? { rows: Array.from({ length: 50 }, (_, row) => ({ employee_id: row + 1, employee_no: `EMP-${row + 1}`, full_name: `Employee ${row + 1}`, arrival_at: null, departure_at: null, worked_minutes: 0, scheduled_minutes: 480, variance_minutes: -480, status: "absent" })), total: 55, page: 1, page_size: 50, has_more: true, search: "", day: "2026-08-17", summary: { employees: 137, present: 112, absent: 25, overtime_minutes: 360 } }
      : { rows: Array.from({ length: 5 }, (_, row) => ({ employee_id: row + 51, employee_no: `EMP-${row + 51}`, full_name: `Employee ${row + 51}`, arrival_at: null, departure_at: null, worked_minutes: 0, scheduled_minutes: 480, variance_minutes: -480, status: "absent" })), total: 55, page: 2, page_size: 50, has_more: false, search: "", day: "2026-08-17", summary: { employees: 137, present: 112, absent: 25, overtime_minutes: 360 } };
    if (new URL(key, "http://local").searchParams.get("search")) {
      page.rows = [{ employee_id: 900, employee_no: "EMP-900", full_name: "Search Match", arrival_at: null, departure_at: null, worked_minutes: 0, scheduled_minutes: 480, variance_minutes: -480, status: "absent" }];
      page.total = 1;
      page.has_more = false;
      page.search = new URL(key, "http://local").searchParams.get("search");
    }
    pages.push(page);
    previousPage = page;
  }
  return { data: pages, error: undefined, isLoading: false, isValidating: false, mutate: async () => {}, setSize: async value => { pageCount = typeof value === "function" ? value(pageCount) : value; } };
}

function createElement(type, props, ...children) {
  return { type, props: { ...(props || {}), children: children.flat() } };
}
globalThis.React = { createElement };

const module = { exports: {} };
if (output) {
  new Function("require", "exports", "module", output)(name => {
    if (name === "react") return { useState };
    if (name === "swr/infinite") return { default: useSWRInfinite };
    if (name === "@/lib/api") return { fetcher: async () => [] };
    if (name === "@/lib/i18n") return { useT: () => ({ t: key => key === "common.loadMore" ? "Load more" : "Search" }) };
    if (name === "@/components/hr/HrUi") return {
      HrHeader: props => createElement("header", props, props.title, props.actions),
      LoadState: props => createElement("load", props, props.children),
      MetricGrid: props => createElement("metrics", props),
    };
    throw new Error(`Unexpected dependency: ${name}`);
  }, module.exports, module);
} else if (globalThis.Bun) {
  globalThis.__attendanceTest = { useState, useSWRInfinite, createElement };
  const mocks = {
    react: "export const useState = (...args) => globalThis.__attendanceTest.useState(...args);",
    "swr/infinite": "const useSWRInfinite = (...args) => globalThis.__attendanceTest.useSWRInfinite(...args); export default useSWRInfinite;",
    "@/lib/api": "export const fetcher = async () => [];",
    "@/lib/i18n": "export const useT = () => ({ t: key => key === 'common.loadMore' ? 'Load more' : 'Search' });",
    "@/components/hr/HrUi": "export const HrHeader = props => globalThis.__attendanceTest.createElement('header', props, props.title, props.actions); export const LoadState = props => globalThis.__attendanceTest.createElement('load', props, props.children); export const MetricGrid = props => globalThis.__attendanceTest.createElement('metrics', props);",
    "react/jsx-dev-runtime": "export const jsxDEV = (type, props) => typeof type === 'function' ? type(props) : { type, props }; export const jsx = (type, props) => typeof type === 'function' ? type(props) : { type, props }; export const jsxs = jsx; export const Fragment = Symbol.for('fragment');",
    "react/jsx-runtime": "export const jsx = (type, props) => typeof type === 'function' ? type(props) : { type, props }; export const jsxs = jsx; export const Fragment = Symbol.for('fragment');",
  };
  const result = await Bun.build({
    entrypoints: [fileURLToPath(new URL("../src/app/(app)/hr/attendance/page.tsx", import.meta.url))],
    target: "bun",
    write: false,
    plugins: [{
      name: "attendance-pagination-test-mocks",
      setup(build) {
        build.onResolve({ filter: /^(react(?:\/jsx(?:-dev)?-runtime)?|swr\/infinite|@\/lib\/api|@\/lib\/i18n|@\/components\/hr\/HrUi)$/ }, args => ({ path: args.path, namespace: "attendance-test" }));
        build.onLoad({ filter: /.*/, namespace: "attendance-test" }, args => ({ contents: mocks[args.path], loader: "js" }));
      },
    }],
  });
  assert.ok(result.success, result.logs.map(log => log.message).join("\n"));
  const bundle = await result.outputs[0].text();
  module.exports.default = (await import(`data:text/javascript;base64,${Buffer.from(bundle).toString("base64")}`)).default;
} else {
  throw new Error("Install frontend development dependencies to run this component behavior test.");
}

function walk(tree, predicate) {
  if (!tree || typeof tree !== "object") return undefined;
  if (predicate(tree)) return tree;
  const children = [tree.props?.children, tree.props?.actions].flatMap(value => Array.isArray(value) ? value : [value]);
  for (const child of children) {
    const found = walk(child, predicate);
    if (found) return found;
  }
  return undefined;
}

function text(tree) {
  if (tree == null || typeof tree === "boolean") return "";
  if (typeof tree === "string" || typeof tree === "number") return String(tree);
  const children = [tree.props?.children, tree.props?.actions].flatMap(value => Array.isArray(value) ? value : [value]).map(text).join("");
  const metrics = (tree.props?.items || []).map(item => `${item.label}${item.value}`).join("");
  return children + metrics;
}

function render() {
  hookIndex = 0;
  return module.exports.default();
}

let tree = render();
assert.equal(keys.length, 1);
let request = new URL(keys[0], "http://local");
assert.equal(request.pathname, "/api/hr/attendance");
assert.equal(request.searchParams.get("page"), "1");
assert.equal(request.searchParams.get("page_size"), "50");
assert.match(text(tree), /Loaded 50 of 55 employees/);
assert.match(text(tree), /Employees137/);
assert.match(text(tree), /Present112/);
assert.match(text(tree), /Absent25/);
assert.match(text(tree), /Overtime6h 0m/);

const loadMore = walk(tree, node => node.type === "button" && text(node) === "Load more");
assert.ok(loadMore, "the next employee page must be reachable");
await loadMore.props.onClick();
keys.length = 0;
tree = render();
assert.equal(keys.length, 2);
assert.equal(new URL(keys[1], "http://local").searchParams.get("page"), "2");
assert.match(text(tree), /Employee 55/);
assert.match(text(tree), /Loaded 55 of 55 employees/);
assert.equal(walk(tree, node => node.type === "button" && text(node) === "Load more"), undefined);

const search = walk(tree, node => node.type === "input" && node.props.type === "search");
assert.ok(search, "server-side employee search must be available");
search.props.onChange({ target: { value: "EMP-900" } });
keys.length = 0;
tree = render();
request = new URL(keys[0], "http://local");
assert.equal(request.searchParams.get("search"), "EMP-900");
assert.equal(request.searchParams.get("page"), "1", "changing search must restart from page one");
assert.match(text(tree), /Search Match/);
assert.match(text(tree), /Loaded 1 of 1 employees matching/);

console.log("PASS: HR Attendance requests 50-row pages, retains exact factory metrics, searches, and exposes Load more.");
