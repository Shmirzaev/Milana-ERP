import assert from "node:assert/strict";
import fs from "node:fs";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/components/hr/DocumentEmployeeSelect.tsx", import.meta.url), "utf8");
const page = fs.readFileSync(new URL("../src/app/(app)/hr/documents/page.tsx", import.meta.url), "utf8");
assert.match(page, /<DocumentEmployeeSelect[\s\S]*?enabled=\{open\}/);
assert.match(page, /if \(!form\.employee_id\) \{/);
assert.doesNotMatch(page, /useSWR<Employee\[\]>\(open \? "\/api\/employees"/);
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const state = [];
let cursor = 0;
let size = 1;
let keys = [];
let enabled = false;
let value = null;
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
    for (let page = 0; page < size; page++) {
      const key = getKey(page, pages.at(-1) || null);
      keys.push(key);
      if (!key) break;
      const searching = key.includes("search=UNRELATED");
      const rows = searching ? [{ id: 900, full_name: "Different employee" }]
        : Array.from({ length: page === 10 ? 1 : 50 }, (_, row) => {
          const id = page * 50 + row + 1;
          return { id, full_name: id === 501 ? "Employee beyond old cap" : `Employee ${id}` };
        });
      pages.push({ rows, total: searching ? 1 : 501 });
    }
    return { data: keys[0] ? pages : undefined, size, setSize: next => { size = next; }, isLoading: false, isValidating: false };
  } },
  "@/components/SearchableSelect": { default: SearchableSelect },
  "@/lib/api": { fetcher() {} },
})[name]);

function render() {
  cursor = 0;
  return exports.default({
    enabled, value, selectedEmployee,
    onChange(employee) { selectedEmployee = employee; value = employee?.id || null; },
  }).props;
}

let props = render();
assert.deepEqual(keys, [null], "closed modal must not fetch employee choices");
enabled = true;
props = render();
assert.deepEqual(keys, [null], "closed picker must not fetch employee choices");
props.onOpenChange(true);
props = render();
assert.equal(keys[0], "/api/employees?page=1&page_size=50&search=");
for (let pageNumber = 2; pageNumber <= 11; pageNumber++) {
  props.onLoadMore();
  props = render();
  assert.equal(keys[pageNumber - 1], `/api/employees?page=${pageNumber}&page_size=50&search=`);
}
assert.equal(props.hasMore, false);
const employee501 = props.options.find(option => option.value === 501);
assert.ok(employee501);
props.onChange(501, employee501);
props = render();
assert.equal(props.value, 501);
props.onSearchChange("UNRELATED");
render();
props = render();
assert.equal(keys[0], "/api/employees?page=1&page_size=50&search=UNRELATED");
assert.equal(props.options.find(option => option.value === 501)?.label, "Employee beyond old cap");
props.onOpenChange(false);
props = render();
assert.deepEqual(keys, [null]);
assert.equal(props.value, 501);
enabled = false;
props = render();
assert.deepEqual(keys, [null]);
assert.equal(props.value, 501);
console.log("HR Documents employee picker reaches row 501, preserves selection, and stays idle when closed.");
