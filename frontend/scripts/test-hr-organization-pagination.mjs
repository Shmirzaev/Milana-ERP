import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/hr/organization/page.tsx", import.meta.url), "utf8");
assert.match(source, /page=\$\{page\}&page_size=\$\{PAGE_SIZE\}&search=/, "the screen must request explicit bounded pages and search");
assert.doesNotMatch(source, /useSWR<Response>\("\/api\/hr\/organization"/, "the screen must not use the unbounded legacy request");

const output = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const calls = [];
let swrKey;
let state;
let cursor = 0;
const effects = [];
const employees = Array.from({ length: 50 }, (_, index) => ({
  id: index + 1, employee_no: `EMP-${index + 1}`, full_name: `Employee ${index + 1}`,
  manager_employee_id: null, hr_position_id: null, position: null, status: "active",
}));

function useState(initial) {
  const index = cursor++;
  if (!(index in state)) state[index] = initial;
  return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
}
function useEffect(effect) { effects.push(effect); }
function useMemo(callback) { return callback(); }
function useSWR(key) {
  swrKey = key;
  calls.push(key);
  const url = new URL(key, "http://local");
  const page = Number(url.searchParams.get("page"));
  const search = url.searchParams.get("search");
  const units = search
    ? [{ id: 900, parent_id: null, parent_name: null, manager_employee_id: null, manager_name: null, unit_type: "team", name: `Match ${search}`, code: null, sort_order: 0 }]
    : Array.from({ length: page === 1 ? 50 : 30 }, (_, index) => {
      const id = (page - 1) * 50 + index + 1;
      return { id, parent_id: id === 51 ? 1 : null, parent_name: id === 51 ? "Unit 1" : null,
        manager_employee_id: id === 1 ? 900 : null, manager_name: id === 1 ? "Historical Manager" : null,
        unit_type: "section", name: `Unit ${id}`, code: null, sort_order: id };
    });
  const rows = search ? employees.slice(0, 1) : employees.slice(0, page === 1 ? 50 : 25);
  return {
    data: { units, employees: rows, page, page_size: 50, search: search || "", unit_total: search ? 1 : 80,
      employee_total: search ? 1 : 75, units_have_more: !search && page === 1,
      employees_have_more: !search && page === 1, active_employee_total: 50,
      vacant_employee_total: 10, manager_unit_total: 3 },
    error: undefined, isLoading: false, mutate: async () => {},
  };
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

const module = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "react") return { useState, useEffect, useMemo, createElement };
  if (name === "swr") return { default: useSWR };
  if (name === "@/lib/api") return { api: { post: async (...args) => calls.push(args) }, fetcher: async () => [] };
  if (name === "@/components/Modal") return { default: props => createElement("modal", props, props.children) };
  if (name === "@/components/hr/HrUi") return {
    HrHeader: props => createElement("header", props, props.title, props.actions),
    LoadState: props => createElement("load", props, props.children),
    MetricGrid: props => createElement("metrics", props),
  };
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);

const OrganizationPage = module.exports.default;
state = [];
function render() {
  cursor = 0;
  effects.length = 0;
  const tree = OrganizationPage();
  for (const effect of effects) effect();
  return tree;
}

let tree = render();
tree = render();
assert.match(swrKey, /page=1&page_size=50&search=/);
assert.match(text(tree), /Unit 1/);
assert.match(text(tree), /Historical Manager/, "manager labels cannot depend on the first employee page");
assert.match(text(tree), /80 units · 75 employees/);

const loadMore = walk(tree, node => node.type === "button" && text(node) === "Load more");
assert.ok(loadMore, "more unit or employee rows must be reachable");
loadMore.props.onClick();
tree = render();
tree = render();
assert.match(swrKey, /page=2&page_size=50&search=/);
assert.match(text(tree), /Loaded 80 units and 50 employees/);
assert.match(text(tree), /Unit 51/);

const search = walk(tree, node => node.type === "input" && node.props.type === "search");
assert.ok(search, "a search input must be visible");
search.props.onChange({ target: { value: "EMP-400" } });
tree = render();
tree = render();
assert.match(swrKey, /page=1&page_size=50&search=EMP-400/);
assert.match(text(tree), /1 units · 1 employees match/);
assert.match(text(tree), /Match EMP-400/);
console.log("PASS: HR Organization loads bounded pages, searches, keeps exact totals, and retains manager labels.");
