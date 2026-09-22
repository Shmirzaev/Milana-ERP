import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/hr/positions/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

const position = {
  id: 9, department_id: 4, department_name: "Cutting", name: "Senior Cutter", job_description: null,
  required_skills: ["cutting"], qualification_level: "Senior", grade_level: null,
  salary_min: 100, salary_max: 200, approved_count: 2, occupied_count: 1,
  vacant_count: 1, is_active: true,
};
const calls = [];
let swrKey;
let state;
let cursor = 0;
const effects = [];

function useState(initial) {
  const index = cursor++;
  if (!(index in state)) state[index] = initial;
  return [state[index], value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
}
function useEffect(effect) { effects.push(effect); }
function useSWR(key) {
  swrKey = key;
  calls.push(key);
  return { data: key === "/api/hr/positions" ? [position] : undefined, error: undefined, isLoading: false, mutate: async () => {} };
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
  if (name === "react") return { useState, useEffect, createElement };
  if (name === "swr") return { default: useSWR };
  if (name === "@/lib/api") return { api: { post: async () => {}, patch: async () => {} }, fetcher: async () => [] };
  if (name === "@/components/Modal") return { default: props => createElement("modal", props, props.children) };
  if (name === "@/components/hr/HrUi") return {
    HrHeader: props => createElement("header", props, props.title, props.actions),
    LoadState: props => createElement("load", props, props.children),
    MetricGrid: props => createElement("metrics", props),
  };
  if (name === "@/lib/usePositionDepartments") return {
    usePositionDepartments: editing => { swrKey = editing === null ? null : "/api/departments"; calls.push(swrKey); return { data: swrKey ? [{ id: 4, name: "Cutting" }] : undefined }; },
  };
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);

const PositionsPage = module.exports.default;
state = [];
function render() {
  cursor = 0;
  effects.length = 0;
  const tree = PositionsPage();
  for (const effect of effects) effect();
  return tree;
}

let tree = render();
assert.equal(swrKey, null, "closed position modal must not fetch departments");
assert.match(text(tree), /Senior Cutter/);
assert.match(text(tree), /Cutting/, "position rows carry department labels without fetching the form directory");

const add = walk(tree, node => node.type === "button" && text(node).includes("Add position"));
assert.ok(add, "Add position action should be rendered");
add.props.onClick();
tree = render();
assert.equal(swrKey, "/api/departments", "opening the modal must fetch departments");

const close = walk(tree, node => node.type === "modal");
assert.ok(close?.props.onClose, "modal close handler should be wired");
close.props.onClose();
tree = render();
assert.equal(swrKey, null, "closing the modal must disable the department fetch");
assert.match(text(tree), /Cutting/, "department names from the position response must remain visible after close");

const edit = walk(tree, node => node.type === "button" && text(node).includes("Edit"));
assert.ok(edit, "Edit action should be rendered");
edit.props.onClick();
tree = render();
assert.equal(swrKey, "/api/departments", "editing a position must fetch department choices");
assert.match(text(tree), /Cutting/);
console.log("PASS: HR Positions component preserves department labels across modal open/edit/close transitions.");
