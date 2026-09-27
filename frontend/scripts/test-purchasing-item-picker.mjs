import assert from "node:assert/strict";
import fs from "node:fs";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/components/PurchasingItemAsyncSelect.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS,
  target: ts.ScriptTarget.ES2020,
  jsx: ts.JsxEmit.ReactJSX,
} }).outputText;

const items = {
  materials: Array.from({ length: 51 }, (_, index) => ({
    id: index + 1, sku: `FAB-${index + 1}`, name: `Fabric ${index + 1}`, unit: "kg",
  })),
  accessories: [{ id: 725, sku: "ACC-725", name: "Button 725", unit: "pcs" }],
};
const calls = [];
const state = [];
const sizes = { materials: 1, accessories: 1 };
let stateIndex = 0;
let props = { value: 0, selectedItem: null, onChange: item => {
  props = { ...props, value: item?.id || 0, selectedItem: item };
}, inputId: "item-picker" };

global.window = { setTimeout(callback) { callback(); return 1; }, clearTimeout() {} };
const exports = {};
new Function("exports", "require", output)(exports, name => ({
  react: {
    useState(initial) {
      const index = stateIndex++;
      if (!(index in state)) state[index] = initial;
      return [state[index], next => { state[index] = typeof next === "function" ? next(state[index]) : next; }];
    },
    useEffect(effect) { effect(); },
    useMemo(factory) { return factory(); },
  },
  "react/jsx-runtime": jsxRuntime,
  "swr/infinite": { default: keyFactory => {
    const firstKey = keyFactory(0, null);
    const group = new URL(firstKey, "http://local").searchParams.get("group");
    const pages = [];
    for (let index = 0; index < sizes[group]; index += 1) {
      const key = keyFactory(index, pages.at(-1) || null);
      if (!key) break;
      calls.push(key);
      const query = new URL(key, "http://local").searchParams.get("q").toLowerCase();
      const filtered = items[group].filter(item => `${item.name} ${item.sku}`.toLowerCase().includes(query));
      pages.push(filtered.slice(index * 50, (index + 1) * 50));
    }
    return {
      data: pages, size: sizes[group],
      setSize(next) { sizes[group] = next; },
      isLoading: false, isValidating: false,
    };
  } },
  "@/components/SearchableSelect": { default: () => null },
  "@/lib/api": { fetcher() {} },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
})[name]);

function render() {
  stateIndex = 0;
  const element = exports.default(props);
  return element.props;
}

let select = render();
assert.deepEqual(calls, [
  "/api/inventory/items?group=materials&page=1&page_size=50&q=",
  "/api/inventory/items?group=accessories&page=1&page_size=50&q=",
]);
assert.equal(select.options.length, 52, "only one 50-row materials page and the first accessory page should render");
assert.equal(select.hasMore, true);
select.onLoadMore();
calls.length = 0;
select = render();
assert.ok(calls.includes("/api/inventory/items?group=materials&page=2&page_size=50&q="));
assert.equal(select.options.length, 53, "a later material page must be selectable");
const offPageItem = items.materials[50];
select.onChange(offPageItem.id);
select.onSearchChange("Button");
render(); // The debounced query updates after the search-input render.
calls.length = 0;
select = render();
assert.ok(calls.some(key => key.includes("q=Button")), "search should reach the server");
assert.ok(select.options.some(option => option.value === offPageItem.id), "selection must remain visible after the search pages change");
assert.equal(select.value, offPageItem.id);
assert.equal(props.selectedItem.unit, "kg", "the off-page selected item's unit must remain available to submit");

console.log("PASS: purchasing item picker loads bounded material/accessory pages, searches, and retains selection.");
