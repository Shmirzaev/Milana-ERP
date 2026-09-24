import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";

const ts = createRequire(import.meta.url)("typescript");

const source = fs.readFileSync(new URL("../src/app/(app)/hr/employees/page.tsx", import.meta.url), "utf8");
assert.match(source, /page=\$\{page\}&page_size=\$\{PAGE_SIZE\}&search=/, "the screen must request bounded server-side pages and search");
assert.match(source, /manager-options\?search=.*selected_id=/, "manager options must use a separate bounded directory and retain the selected id");
assert.match(source, /data\.search === query\.trim\(\)/, "stale search responses must not replace the current result set");
assert.match(source, /profile_coverage_percent/, "profile coverage must use the permission-aware exact server metric");
assert.doesNotMatch(source, /useSWR<Employee\[]>\("\/api\/employees"/, "the screen must not fetch the legacy employee list");

const output = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const apiCalls = [];
const keys = [];
let pageData = { rows: [{ id: 1, factory_code: "ECO", employee_no: "1", full_name: "Ada Employee", department_id: null,
  position: "Operator", phone: null, salary: null, status: "active", joined_at: null, manager_employee_id: null,
  manager_name: "Mira Manager", hr_position_id: null, hr_profile_json: { a: 1, b: 2, c: 3, d: 4, e: 5 } }],
  total: 51, page: 1, page_size: 50, has_more: true, active_total: 40, inactive_total: 11, profile_coverage_percent: 25, search: "" };
let staleData;
let managerRows = [{ id: 4, full_name: "Mira Manager" }];
let state;
let cursor = 0;
const effects = [];

function useState(initial) {
  const index = cursor++;
  if (!(index in state)) state[index] = initial;
  return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
}
function useEffect(effect) { effects.push(effect); }
function useMemo(callback) { return callback(); }
function useSWR(key) {
  keys.push(key);
  if (key?.startsWith("/api/employees?page=")) return { data: staleData || pageData, error: undefined, isLoading: false, mutate: async () => { apiCalls.push(["mutate"]); } };
  if (key?.startsWith("/api/employees/manager-options")) {
    managerRows = key.includes("selected_id=4") ? [{ id: 4, full_name: "Mira Manager" }] : managerRows;
    return { data: { rows: managerRows, has_more: false }, error: undefined, isLoading: false };
  }
  return { data: key === "/api/departments" ? [] : undefined, error: undefined, isLoading: false, mutate: async () => {} };
}
function createElement(type, props, ...children) {
  const nextProps = { ...(props || {}), children: children.flat() };
  return typeof type === "function" ? type(nextProps) : { type, props: nextProps };
}
globalThis.React = { createElement };
function walk(tree, predicate) {
  if (!tree || typeof tree !== "object") return undefined;
  if (predicate(tree)) return tree;
  for (const child of tree.props?.children || []) {
    const found = walk(child, predicate);
    if (found) return found;
  }
  return undefined;
}
function text(tree) {
  if (tree == null || typeof tree === "boolean") return "";
  if (typeof tree === "string" || typeof tree === "number") return String(tree);
  return (tree.props?.children || []).map(text).join("");
}
const pageModule = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "react") return { useState, useEffect, useMemo, createElement };
  if (name === "swr") return { default: useSWR };
  if (name === "@/lib/api") return { api: {
    post: async (...args) => { apiCalls.push(args); },
    patch: async (...args) => { apiCalls.push(args); },
  }, fetcher: async () => [] };
  if (name === "@/components/Modal") return { default: props => createElement("modal", props, props.children) };
  if (name === "@/components/hr/HrUi") return {
    HrHeader: props => createElement("header", props, props.title, props.actions),
    LoadState: props => createElement("load", props, props.children),
    MetricGrid: props => createElement("metrics", props, ...props.items.map(item => `${item.label}: ${item.value}`)),
  };
  if (name === "@/lib/i18n") return { useT: () => ({ t: key => key }) };
  throw new Error(`Unexpected dependency: ${name}`);
}, pageModule.exports, pageModule);
const EmployeesPage = pageModule.exports.default;
state = [];
function render() {
  let tree;
  for (let pass = 0; pass < 3; pass += 1) {
    cursor = 0;
    effects.length = 0;
    tree = EmployeesPage();
    const pending = effects.splice(0);
    if (!pending.length) break;
    for (const effect of pending) effect();
  }
  return tree;
}

let tree = render();
assert.ok(keys.some(key => key?.includes("/api/employees?page=1&page_size=50&search=")));
assert.match(text(tree), /Mira Manager/, "table manager names come with each paged employee row");
assert.match(text(tree), /51/);
  assert.ok(walk(tree, node => node.type === "button" && text(node) === "page.hrEmployees.loadMore"));

const add = walk(tree, node => node.type === "button" && text(node).includes("Add employee"));
add.props.onClick();
tree = render();
let managerLabel = walk(tree, node => node.type === "label" && text(node).includes("page.hrEmployees.manager—"));
let managerSelect = walk(managerLabel, node => node.type === "select");
managerSelect.props.onChange({ target: { value: "4" } });
tree = render();
assert.ok(keys.some(key => key?.includes("selected_id=4")), "the current selection must be hydrated outside the visible page");
const managerSearch = walk(tree, node => node.type === "input" && node.props.placeholder === "page.payroll.searchEmployee");
managerSearch.props.onChange({ target: { value: "Mira" } });
tree = render();
assert.ok(keys.some(key => key?.includes("search=Mira&selected_id=4")), "changing the query must keep the selected manager in the options response");
const employeeForm = walk(tree, node => node.type === "form");
await employeeForm.props.onSubmit({ preventDefault() {} });
assert.ok(apiCalls.some(call => call[0] === "/api/employees"), "saving must retain the existing employee create workflow");
assert.ok(apiCalls.some(call => call[0] === "mutate"), "a successful save on page one must refresh the employee page");
tree = render();
assert.equal(walk(tree, node => node.type === "modal")?.props.open, false, "the editor closes after a successful save");

const employeeSearch = walk(tree, node => node.type === "input" && node.props.placeholder === "Search by employee ID, name or position");
employeeSearch.props.onChange({ target: { value: "missing" } });
staleData = pageData;
tree = render();
assert.doesNotMatch(text(tree), /page.hrEmployees.loadMore/, "stale page data must not expose load-more for a different query");
assert.match(text(tree), /—/, "stale summary values must be cleared while the current search loads");
staleData = undefined;
pageData = { ...pageData, rows: [], total: 0, active_total: 0, inactive_total: 0, profile_coverage_percent: 0, has_more: false, search: "missing" };
tree = render();
assert.match(keys.find(key => key?.includes("page_size=50&search=missing")), /search=missing/);

console.log("PASS: HR Employees uses bounded server search, exact page metrics, row manager labels, stale-response guards, and selected manager lookup.");
