import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/components/BrandAsyncSelect.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const jsx = (type, props) => ({ type, props: props || {} });
const requests = [];
const sizes = [];
const chosen = [];
const dependencies = {
  react: {
    useState: (initial) => [initial, () => {}],
    useEffect() {},
    useMemo: (compute) => compute(),
  },
  "react/jsx-runtime": { jsx, jsxs: jsx },
  swr: { default: (key) => {
    requests.push(key);
    return { data: { id: 777, name: "Brand beyond first 500" } };
  } },
  "swr/infinite": { default: (getKey) => {
    requests.push(getKey(0, null));
    assert.equal(getKey(1, { rows: [], total: 777, has_more: false }), null);
    return {
      data: [{ rows: [{ id: 1, name: "First brand" }], total: 777, has_more: true }],
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
new Function("require", "exports", "module", compiled)((name) => {
  assert.ok(name in dependencies, `Unexpected dependency ${name}`);
  return dependencies[name];
}, testModule.exports, testModule);

const tree = testModule.exports.default({
  value: 777,
  onChange: (id) => chosen.push(id),
  inputId: "collection-edit-brand",
});
assert.equal(requests[0], "/api/brands?page=1&page_size=50&q=");
assert.equal(requests[1], "/api/brands/777");
assert.deepEqual(tree.props.options, [
  { value: 777, label: "Brand beyond first 500" },
  { value: 1, label: "First brand" },
]);
assert.equal(tree.props.value, 777);
assert.equal(tree.props.serverFilter, true);
assert.equal(tree.props.hasMore, true);
tree.props.onLoadMore();
assert.deepEqual(sizes, [2]);
tree.props.onChange(1);
assert.deepEqual(chosen, [1]);
console.log("PASS: Collections brand picker preserves an off-page selection and loads bounded brand pages.");
