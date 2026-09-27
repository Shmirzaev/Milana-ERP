import assert from "node:assert/strict";
import fs from "node:fs";
import * as jsxRuntime from "react/jsx-runtime";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/components/CuttingProductionOrderSelect.tsx", import.meta.url), "utf8");
const pageSource = fs.readFileSync(new URL("../src/app/(app)/cutting-passports/page.tsx", import.meta.url), "utf8");
const backendTest = fs.readFileSync(new URL("../../backend/app/tests/test_production_order_pagination.py", import.meta.url), "utf8");
assert.match(pageSource, /selectedOrder=\{currentProductionOrder\} cuttingDepartment=\{cuttingDepartment\}/,
  "edited off-page order identity must be retained in the actual form");
assert.match(pageSource, /showForm && form\.production_order_id/, "off-page order detail must load only in the open form");
assert.match(backendTest, /test_cutting_passport_order_pages_scope_factory_before_count_and_limit/,
  "backend regression must exercise factory SQL filtering before its page limit");

const output = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const all = Array.from({ length: 401 }, (_, index) => ({
  id: index + 1, production_no: `PO-${String(index + 1).padStart(5, "0")}`,
}));
const states = [];
let stateIndex = 0;
let size = 1;
let previousScope = "";
const keys = [];
let props = {
  value: 0, selectedOrder: null, cuttingDepartment: "CUT", inputId: "cutting-po",
  onChange: order => { props = { ...props, value: order?.id || 0, selectedOrder: order }; },
};
global.window = { setTimeout(callback) { callback(); return 1; }, clearTimeout() {} };
const exports = {};
new Function("exports", "require", output)(exports, name => ({
  react: {
    useState(initial) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = initial;
      return [states[index], next => { states[index] = typeof next === "function" ? next(states[index]) : next; }];
    },
    useEffect(effect) { effect(); },
    useMemo(factory) { return factory(); },
  },
  "react/jsx-runtime": jsxRuntime,
  "swr/infinite": { default: keyFactory => {
    const first = keyFactory(0, null);
    const params = new URL(first, "http://local").searchParams;
    const scope = `${params.get("cutting_department_code")}:${params.get("q")}`;
    if (scope !== previousScope) { size = 1; previousScope = scope; }
    const department = params.get("cutting_department_code");
    const query = params.get("q")?.toLowerCase() || "";
    const filtered = all.filter(order => (department === "ECT" ? order.id > 200 : order.id <= 200)
      && order.production_no.toLowerCase().includes(query));
    const pages = [];
    for (let index = 0; index < size; index += 1) {
      const key = keyFactory(index, pages.at(-1) || null);
      if (!key) break;
      keys.push(key);
      pages.push({ rows: filtered.slice(index * 50, (index + 1) * 50), total: filtered.length,
        has_more: (index + 1) * 50 < filtered.length });
    }
    return { data: pages, size, setSize(next) { size = next; }, isLoading: false, isValidating: false };
  } },
  "@/components/SearchableSelect": { default: () => null },
  "@/lib/api": { fetcher() {} },
  "@/lib/i18n": { useT: () => ({ t: key => key }) },
  "@/lib/orderRef": { orderReference: order => order.production_no },
})[name]);

function render() { stateIndex = 0; return exports.default(props).props; }

let select = render();
assert.equal(select.options.length, 51);
assert.equal(select.hasMore, true);
assert.deepEqual(keys, ["/api/production-orders?cutting_department_code=CUT&page=1&page_size=50&include_total=true&q="]);
select.onLoadMore();
keys.length = 0;
select = render();
assert.equal(select.options.length, 101);
assert.ok(keys.includes("/api/production-orders?cutting_department_code=CUT&page=2&page_size=50&include_total=true&q="));
select.onChange(51);
assert.equal(props.selectedOrder.id, 51);
select.onSearchChange("PO-00002");
render(); // Debounced query becomes active after this render.
keys.length = 0;
select = render();
assert.equal(select.hasMore, false);
assert.equal(keys.length, 1, "search must reset the page count");
assert.ok(keys[0].endsWith("&q=PO-00002"));
assert.ok(select.options.some(option => option.value === 51), "selected off-page order must stay visible");

props = { ...props, cuttingDepartment: "ECT", value: 0, selectedOrder: null };
keys.length = 0;
select = render();
assert.equal(select.hasMore, false, "search remains scoped to the new factory");
assert.ok(keys[0].includes("cutting_department_code=ECT"));

console.log("PASS: cutting order picker searches bounded factory pages and retains an off-page selection.");
