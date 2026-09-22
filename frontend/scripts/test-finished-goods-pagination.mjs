import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/finished-goods/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

let stateIndex = 0;
let stockSize = 1;
let brandedSize = 1;
const setSizeCalls = [];
const stockPages = [[{ id: 2, model_code: "A" }, ...Array.from({ length: 499 }, (_, i) => ({ id: 100 + i, model_code: `S${i}` }))], [{ id: 1, model_code: "B" }]];
const brandedPages = [[{ id: 4, brand_name: "X" }, ...Array.from({ length: 499 }, (_, i) => ({ id: 1000 + i, brand_name: `BR${i}` }))], [{ id: 3, brand_name: "Y" }]];
function useSWR(initial) {
  return { data: initial.includes("inbox") ? {} : undefined };
}
function useSWRInfinite(keyFactory) {
  const first = keyFactory(0);
  const branded = first.includes("branded-stock");
  const size = branded ? brandedSize : stockSize;
  const pages = (branded ? brandedPages : stockPages).slice(0, size);
  return { data: pages, size, setSize: async value => { setSizeCalls.push(value); if (branded) brandedSize = value; else stockSize = value; } };
}
function jsx(type, props) { return { type, props: props || {} }; }
const noop = () => null;
const module = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "react") return {};
  if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
  if (name === "swr") return Object.assign(noop, { default: useSWR, useSWRInfinite });
  if (name === "next/link") return noop;
  if (name === "@/lib/api") return { fetcher: async () => ({}) };
  if (name === "@/lib/i18n") return { useT: () => ({ lang: "en", t: key => key }) };
  if (name === "@/lib/orderRef") return { formatOrderReference: value => String(value) };
  if (name === "@/components/PageHeader") return { default: noop };
  if (name === "@/components/StocktakeLink") return { default: noop };
  if (name === "@/components/ShipmentItemLines") return { default: noop };
  if (name === "@/components/StagePipeline") return { statusLabel: value => value };
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);
const Page = module.exports.default;
function walk(node, predicate, found = []) {
  if (!node || typeof node !== "object") return found;
  if (predicate(node)) found.push(node);
  for (const child of Object.values(node.props || {})) {
    if (Array.isArray(child)) child.forEach(item => walk(item, predicate, found));
    else walk(child, predicate, found);
  }
  return found;
}
function containsText(value, text) {
  if (value === text) return true;
  if (Array.isArray(value)) return value.some(item => containsText(item, text));
  return Boolean(value && typeof value === "object" && containsText(value.props?.children, text));
}
function render() { stateIndex = 0; return Page(); }

let tree = render();
assert.equal(stockPages[0].length, 500);
const buttons = walk(tree, node => node.type === "button" && containsText(node.props.children, "Load more"));
assert.equal(buttons.length, 2, "both lists expose load-more while another page exists");
await buttons[0].props.onClick();
await buttons[1].props.onClick();
assert.deepEqual(setSizeCalls, [2, 2], "stock and branded load-more call their own SWR pagination");
tree = render();
assert(containsText(tree, "A") && containsText(tree, "B"), "stock pages aggregate into one table");
assert(containsText(tree, "X") && containsText(tree, "Y"), "branded pages aggregate into one table");
console.log("PASS: Finished Goods stock and branded SWR pagination/load-more execute and aggregate pages.");
