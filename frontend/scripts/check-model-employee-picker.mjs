import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/components/ModelEmployeeAsyncSelect.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../src/app/(app)/models/[id]/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(page, /useSWR<any\[]>\("\/api\/employees"/);
assert.equal((page.match(/<ModelEmployeeAsyncSelect/g) || []).length, 2);
assert.match(page, /constructor: constructorName/);
assert.match(page, /designer: designerName/);
assert.match(page, /`\/api\/employees\/\$\{modelForm\.constructor_employee_id\}`/);
assert.match(page, /`\/api\/employees\/\$\{modelForm\.designer_employee_id\}`/);
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const state = [];
let cursor = 0;
let size = 1;
let keys = [];
let value = 0;
let selectedEmployee = null;
global.window = { setTimeout: callback => { callback(); return 1; }, clearTimeout() {} };
const hooks = {
  ...React,
  useMemo(factory) { return factory(); },
  useEffect(effect) { effect(); },
  useState(initial) {
    const slot = cursor++;
    if (!(slot in state)) state[slot] = typeof initial === "function" ? initial() : initial;
    return [state[slot], next => { state[slot] = typeof next === "function" ? next(state[slot]) : next; }];
  },
};
const SearchableSelect = () => null;
const exports = {};
new Function("exports", "require", output)(exports, name => ({
  react: hooks,
  "react/jsx-runtime": jsxRuntime,
  "swr/infinite": { default: getKey => {
    const pages = [];
    keys = [];
    for (let pageNumber = 0; pageNumber < size; pageNumber++) {
      const key = getKey(pageNumber, pages.at(-1) || null);
      keys.push(key);
      if (!key) break;
      const searching = key.includes("search=UNRELATED");
      const rows = searching ? [{ id: 900, full_name: "Unrelated employee", department_id: 2 }]
        : Array.from({ length: pageNumber === 10 ? 1 : 50 }, (_, row) => {
          const id = pageNumber * 50 + row + 1;
          return { id, full_name: id === 501 ? "Late model constructor" : `Employee ${id}`, department_id: id % 2 ? 1 : 2 };
        });
      pages.push({ rows, total: searching ? 1 : 501 });
    }
    return { data: keys[0] ? pages : undefined, size, setSize: next => { size = next; }, isLoading: false, isValidating: false };
  } },
  "@/components/SearchableSelect": { default: SearchableSelect },
  "@/lib/api": { fetcher() {} },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
})[name]);

function render(enabled = true) {
  cursor = 0;
  return exports.default({
    enabled, value, selectedEmployee, departmentIds: new Set([1]),
    inputId: "model-constructor", placeholder: "Constructor",
    onChange(employee) { selectedEmployee = employee; value = employee?.id || 0; },
  }).props;
}

let props = render();
assert.deepEqual(keys, [null]);
props.onOpenChange(true);
props = render();
assert.equal(keys[0], "/api/employees?page=1&page_size=50&search=");
assert.ok(props.options.some(option => option.value === 1));
assert.ok(!props.options.some(option => option.value === 2), "non-modeling departments stay excluded");
for (let page = 2; page <= 11; page++) {
  props.onLoadMore();
  props = render();
  assert.equal(keys[page - 1], `/api/employees?page=${page}&page_size=50&search=`);
}
const lateEmployee = props.options.find(option => option.value === 501);
assert.ok(lateEmployee, "employee 501 must be selectable");
props.onChange(501, lateEmployee);
props = render();
assert.equal(props.value, 501);
props.onSearchChange("UNRELATED");
render();
props = render();
assert.equal(keys[0], "/api/employees?page=1&page_size=50&search=UNRELATED");
assert.equal(props.options.find(option => option.value === 501)?.label, "Late model constructor");
assert.ok(!props.options.some(option => option.value === 900));
props.onOpenChange(false);
props = render();
assert.deepEqual(keys, [null]);
assert.equal(props.value, 501);
props = render(false);
assert.deepEqual(keys, [null]);
console.log("Model employee picker reaches employee 501, preserves names, and filters departments.");
