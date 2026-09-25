import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/brands/page.tsx", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

const state = [];
let cursor = 0;
const requests = [];
const jsx = (type, props) => ({ type, props: props || {} });
const dependencies = {
  react: {
    useState(initial) {
      const index = cursor++;
      if (!(index in state)) state[index] = initial;
      return [state[index], (value) => { state[index] = value; }];
    },
    useEffect() {},
  },
  "react/jsx-runtime": { jsx, jsxs: jsx },
  "next/navigation": { useSearchParams: () => ({ get: (key) => key === "q" ? "needle" : null }) },
  swr: { default: (key) => {
    requests.push(key);
    const page = Number(new URL(key, "http://test.local").searchParams.get("page"));
    return { data: {
      rows: [{ id: page, name: `Needle ${page}`, description: "", is_active: true }],
      total: 101, page, page_size: 50, has_more: page < 3,
    }, mutate() {} };
  } },
  "@/lib/api": { api: {}, fetcher() {} },
  "@/components/PageHeader": { default: "page-header" },
  "@/components/PaginationControls": { default: "pagination-controls" },
  "@/components/Modal": { default: "modal" },
  "@/lib/auth": { useMe: () => ({ me: null }), can: () => false },
  "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
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
assert.equal(requests[0], "/api/brands?page=1&page_size=50&q=needle");
let controls = visit(tree, (node) => node.type === "pagination-controls")[0].props;
assert.equal(controls.total, 101);
assert.equal(controls.count, 1);
assert.ok(visit(tree, (node) => node.props?.children === "Needle 1").length);

controls.onPageChange(2);
tree = render();
assert.equal(requests.at(-1), "/api/brands?page=2&page_size=50&q=needle");
assert.ok(visit(tree, (node) => node.props?.children === "Needle 2").length);

controls = visit(tree, (node) => node.type === "pagination-controls")[0].props;
controls.onPageSizeChange(25);
render();
assert.equal(requests.at(-1), "/api/brands?page=1&page_size=25&q=needle");
console.log("PASS: Brands screen requests bounded searched pages and renders exact totals.");
