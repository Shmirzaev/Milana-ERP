import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const screen = fs.readFileSync(new URL("../src/app/(app)/inventory/receive/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(screen, /useSWR<[^>]+>\("\/api\/suppliers"/,
  "Receive Stock must not request the entire supplier directory");
assert.match(screen, /<SupplierAsyncSelect[\s\S]*?value=\{form\.supplier_id \|\| null\}/,
  "both Receive Stock forms must preserve their selected supplier");

const source = fs.readFileSync(new URL("../src/components/SupplierAsyncSelect.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const state = [];
const timers = [];
const requests = [];
const sizes = [];
const chosen = [];
let cursor = 0;
const jsx = (type, props) => ({ type, props: props || {} });
const dependencies = {
  react: {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], (value) => { state[index] = value; }];
    },
    useEffect: (effect) => effect(),
    useMemo: (compute) => compute(),
  },
  "react/jsx-runtime": { jsx, jsxs: jsx },
  swr: { default: (key) => {
    requests.push(key);
    return { data: { id: 777, name: "Selected supplier beyond first page" } };
  } },
  "swr/infinite": { default: (getKey) => {
    requests.push(getKey(0, null));
    assert.equal(getKey(1, { rows: [], total: 777, has_more: false }), null);
    return {
      data: [{ rows: [{ id: 1, name: "First supplier" }], total: 777, has_more: true }],
      size: 1,
      setSize: (size) => sizes.push(size),
      isLoading: false,
      isValidating: false,
    };
  } },
  "@/components/SearchableSelect": { default: "searchable-select" },
  "@/lib/api": { fetcher() {} },
  "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
};
const testModule = { exports: {} };
new Function("require", "exports", "module", "window", compiled)((name) => {
  assert.ok(name in dependencies, `Unexpected dependency ${name}`);
  return dependencies[name];
}, testModule.exports, testModule, {
  setTimeout: (callback) => { timers.push(callback); return timers.length; },
  clearTimeout() {},
});
function render() {
  cursor = 0;
  return testModule.exports.default({
    value: 777,
    onChange: (id) => chosen.push(id),
    inputId: "stock-receive-supplier",
  });
}

let tree = render();
assert.equal(requests[0], "/api/suppliers?page=1&page_size=50&q=");
assert.equal(requests[1], "/api/suppliers/777");
assert.deepEqual(tree.props.options, [
  { value: 0, label: "ph.supplier" },
  { value: 777, label: "Selected supplier beyond first page" },
  { value: 1, label: "First supplier" },
]);
assert.equal(tree.props.value, 777);
tree.props.onLoadMore();
assert.deepEqual(sizes, [2]);
tree.props.onChange(0);
assert.deepEqual(chosen, [0], "the optional supplier can be cleared");

tree.props.onSearchChange("needle");
render();
timers.at(-1)();
tree = render();
assert.ok(requests.includes("/api/suppliers?page=1&page_size=50&q=needle"));
assert.equal(tree.props.value, 777, "search must not discard an off-page selection");
console.log("PASS: Receive Stock supplier picker searches bounded pages and preserves its selection.");
