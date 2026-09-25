import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/collections/page.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const state = [];
const requests = [];
let cursor = 0;
const jsx = (type, props) => ({ type, props: props || {} });
const dependencies = {
  react: {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], (value) => { state[index] = value; }];
    },
    useEffect() {},
    useMemo: (compute) => compute(),
  },
  "react/jsx-runtime": { jsx, jsxs: jsx },
  "next/navigation": { useSearchParams: () => ({ get: (key) => key === "q" ? "needle" : null }) },
  swr: { default: (key) => {
    requests.push(key);
    if (key?.startsWith("/api/brands?")) return { data: { rows: [{ id: 9, name: "Needle Brand" }] } };
    const page = Number(new URL(key, "http://test.local").searchParams.get("page"));
    return { data: {
      rows: [{ id: page, brand_id: 9, name: `Season ${page}`, year: 2090, status: "draft" }],
      total: 101, page, page_size: 50,
    }, mutate() {} };
  } },
  "@/lib/api": { api: {}, fetcher() {} },
  "@/components/PageHeader": { default: "page-header" },
  "@/components/PaginationControls": { default: "pagination-controls" },
  "@/components/Modal": { default: "modal" },
  "@/components/BrandAsyncSelect": { default: "brand-select" },
  "@/components/StagePipeline": { statusLabel: (value) => value },
  "@/lib/auth": { useMe: () => ({ me: null }), can: () => false },
  "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
  "@/lib/numberInput": { numberOrFallback: Number, parseNumberInput: (value) => value },
};
const testModule = { exports: {} };
new Function("require", "exports", "module", compiled)((name) => {
  assert.ok(name in dependencies, `Unexpected dependency ${name}`);
  return dependencies[name];
}, testModule.exports, testModule);

function visit(node, predicate, found = []) {
  if (Array.isArray(node)) {
    for (const child of node) visit(child, predicate, found);
  } else if (node && typeof node === "object") {
    if (predicate(node)) found.push(node);
    visit(node.props?.children, predicate, found);
  }
  return found;
}
function render() { cursor = 0; return testModule.exports.default(); }

let tree = render();
assert.ok(requests.includes("/api/collections?page=1&page_size=50&q=needle"));
assert.ok(requests.includes("/api/brands?page=1&page_size=50&ids=9"));
let controls = visit(tree, (node) => node.type === "pagination-controls")[0].props;
assert.equal(controls.total, 101);
assert.equal(controls.count, 1);
assert.ok(visit(tree, (node) => node.props?.children === "Season 1").length,
  "a match on brand name must remain visible even when the collection name differs");
assert.ok(visit(tree, (node) => node.props?.children === "Needle Brand").length,
  "the page must resolve the visible collection's brand without the capped legacy brand list");

controls.onPageChange(2);
tree = render();
assert.ok(requests.includes("/api/collections?page=2&page_size=50&q=needle"));
assert.ok(visit(tree, (node) => node.props?.children === "Season 2").length);

controls = visit(tree, (node) => node.type === "pagination-controls")[0].props;
controls.onPageSizeChange(25);
render();
assert.ok(requests.includes("/api/collections?page=1&page_size=25&q=needle"));
console.log("PASS: Collections screen pages server-filtered rows with exact totals.");
