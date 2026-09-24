import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/admin/data/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

const departmentColumns = [
  { name: "id", type: "INTEGER", nullable: false, primary_key: true, foreign_key: null, editable: false },
  { name: "name", type: "VARCHAR(128)", nullable: false, primary_key: false, foreign_key: null, editable: true },
  { name: "code", type: "VARCHAR(32)", nullable: false, primary_key: false, foreign_key: null, editable: false },
];
const userColumns = [
  { name: "id", type: "INTEGER", nullable: false, primary_key: true, foreign_key: null, editable: false },
  { name: "password_hash", type: "VARCHAR(255)", nullable: false, primary_key: false, foreign_key: null, editable: false },
];
const tables = [
  { name: "departments", label: "Departments", columns: departmentColumns },
  { name: "users", label: "Users", columns: userColumns },
];
const patches = [];
const swrKeys = [];
let state = [];
let cursor = 0;
const effects = [];

function useState(initial) {
  const index = cursor++;
  if (!(index in state)) state[index] = initial;
  return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
}
function useEffect(effect) { effects.push(effect); }
function useMemo(factory) { return factory(); }
function useSWR(key) {
  swrKeys.push(key);
  if (key === "/api/admin/super-data/tables/directory") {
    return { data: tables, mutate: async () => {} };
  }
  if (key?.includes("/departments?")) {
    return { data: { table: "departments", label: "Departments", columns: departmentColumns, rows: [{ id: 7, name: "Old", code: "CUT" }], total: 1, page: 1, page_size: 50 }, mutate: async () => {}, isLoading: false };
  }
  if (key?.includes("/users?")) {
    return { data: { table: "users", label: "Users", columns: userColumns, rows: [{ id: 2, password_hash: "secret" }], total: 1, page: 1, page_size: 50 }, mutate: async () => {}, isLoading: false };
  }
  return { data: undefined, mutate: async () => {}, isLoading: false };
}
function createElement(type, props, ...children) {
  const nextProps = { ...(props || {}), children: children.flat() };
  return typeof type === "function" ? type(nextProps) : { type, props: nextProps };
}
globalThis.React = { createElement };

function walkAll(tree, predicate, found = []) {
  if (!tree || typeof tree !== "object") return found;
  if (predicate(tree)) found.push(tree);
  for (const child of tree.props?.children || []) walkAll(child, predicate, found);
  return found;
}

const runtimeModule = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "react") return { useState, useEffect, useMemo, createElement };
  if (name === "swr") return { default: useSWR };
  if (name === "lucide-react") return new Proxy({}, { get: () => props => createElement("icon", props) });
  if (name === "@/lib/api") return { api: { patch: async (...args) => { patches.push(args); } }, fetcher: async () => [] };
  if (name === "@/components/Modal") return { default: props => props.open ? createElement("modal", props, props.children) : null };
  if (name === "@/components/PageHeader") return { default: props => createElement("header", props, props.actions) };
  if (name === "@/lib/i18n") return { useT: () => ({ t: (key, values) => values ? `${key}:${JSON.stringify(values)}` : key }) };
  throw new Error(`Unexpected dependency: ${name}`);
}, runtimeModule.exports, runtimeModule);

const Page = runtimeModule.exports.default;
function render() {
  cursor = 0;
  effects.length = 0;
  const tree = Page();
  for (const effect of effects) effect();
  return tree;
}

state = ["departments"];
let tree = render();
assert.ok(swrKeys.includes("/api/admin/super-data/tables/directory"), "table directory counts must be loaded only with the selected table");
let editButtons = walkAll(tree, node => node.type === "button" && node.props?.title === "common.edit");
assert.equal(editButtons.length, 1, "departments should expose the backend-approved name repair action");
assert.equal(walkAll(tree, node => node.type === "button" && node.props?.title === "common.delete").length, 0, "hard delete must not be rendered");

editButtons[0].props.onClick();
tree = render();
const nameInput = walkAll(tree, node => node.type === "input" && node.props?.value === "Old")[0];
assert.ok(nameInput, "the approved department name must be editable");
nameInput.props.onChange({ target: { value: "Renamed" } });
tree = render();
const editForm = walkAll(tree, node => node.type === "form" && typeof node.props?.onSubmit === "function").at(-1);
await editForm.props.onSubmit({ preventDefault() {} });
assert.deepEqual(patches, [["/api/admin/super-data/repairs/departments/7/rename", { name: "Renamed" }]]);

state = ["users"];
tree = render();
assert.equal(walkAll(tree, node => node.type === "button" && node.props?.title === "common.edit").length, 0, "read-only tables must not render an edit action");
assert.equal(walkAll(tree, node => node.type === "button" && node.props?.title === "common.delete").length, 0, "read-only tables must not render delete");

console.log("PASS: Data Console renders only the approved department-name repair and never exposes hard delete.");
