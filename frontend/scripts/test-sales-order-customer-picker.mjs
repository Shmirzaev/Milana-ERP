import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const screen = fs.readFileSync(new URL("../src/app/(app)/sales-orders/new/page.tsx", import.meta.url), "utf8");
assert.doesNotMatch(screen, /useSWR<Customer\[\]>/, "New Sales Order must not load the full customer directory");
assert.match(screen, /<CustomerAsyncSelect[\s\S]*selectedCustomer=\{selectedCustomer\}/);
assert.match(screen, /setSelectedCustomer\(created\)/, "a newly created customer must retain its name immediately");

const source = fs.readFileSync(new URL("../src/components/CustomerAsyncSelect.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const state = [];
const timers = [];
const requests = [];
const sizes = [];
const chosen = [];
let cursor = 0;
let selectedCustomer = null;
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
    return { data: key ? { id: 777, name: "Off-page customer" } : undefined };
  } },
  "swr/infinite": { default: (getKey) => {
    requests.push(getKey(0, null));
    assert.equal(getKey(1, { rows: [], total: 50, page: 1, page_size: 50 }), null);
    assert.match(getKey(1, { rows: [], total: 51, page: 1, page_size: 50 }), /^\/api\/customers\?page=2&page_size=50&q=/);
    return {
      data: [{ rows: [{ id: 1, name: "First customer" }], total: 777, page: 1, page_size: 50 }],
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
    selectedCustomer,
    onChange: (id, customer) => chosen.push({ id, customer }),
  });
}

let tree = render();
assert.equal(requests[0], "/api/customers?page=1&page_size=50&q=");
assert.equal(requests[1], "/api/customers/777");
assert.deepEqual(tree.props.options, [
  { value: 0, label: "newso.customerSelect" },
  { value: 777, label: "Off-page customer" },
  { value: 1, label: "First customer" },
]);
assert.equal(tree.props.value, 777);
assert.equal(tree.props.hasMore, true);
tree.props.onLoadMore();
assert.deepEqual(sizes, [2]);
tree.props.onChange(0);
assert.deepEqual(chosen, [{ id: null, customer: undefined }], "customer remains optional");

tree.props.onSearchChange("needle");
render();
timers.at(-1)();
tree = render();
assert.ok(requests.includes("/api/customers?page=1&page_size=50&q=needle"));
assert.equal(tree.props.value, 777, "search must retain an off-page selection");

selectedCustomer = { id: 777, name: "Newly created customer" };
requests.length = 0;
tree = render();
assert.equal(requests.includes("/api/customers/777"), false);
assert.ok(tree.props.options.some((option) => option.value === 777 && option.label === "Newly created customer"));
console.log("PASS: New Sales Order customer picker uses bounded pages and preserves existing and newly created selections.");
