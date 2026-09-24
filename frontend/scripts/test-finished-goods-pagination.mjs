import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/app/(app)/finished-goods/page.tsx", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

let stockSize = 1;
let brandedSize = 1;
let readyToShipSize = 1;
const setSizeCalls = [];
const readyToShip = { sales_order_id: 9, sales_order_no: "SO-9" };
const readyToShipPages = [[{ ...readyToShip }], [{ sales_order_id: 10, sales_order_no: "SO-10" }]];
const stockPages = [[{ id: 2, model_code: "A" }, ...Array.from({ length: 499 }, (_, i) => ({ id: 100 + i, model_code: `S${i}` }))], [{ id: 1, model_code: "B" }]];
const brandedPages = [[{ id: 4, brand_name: "X" }, ...Array.from({ length: 499 }, (_, i) => ({ id: 1000 + i, brand_name: `BR${i}` }))], [{ id: 3, brand_name: "Y" }]];
function useSWRInfinite(keyFactory) {
  const first = keyFactory(0);
  const branded = first.includes("branded-stock");
  const ready = first.includes("ready_to_ship_limit");
  const size = ready ? readyToShipSize : branded ? brandedSize : stockSize;
  const pages = (ready ? readyToShipPages : branded ? brandedPages : stockPages).slice(0, size);
  return {
    data: ready ? pages.map((page) => ({ ready_to_ship: page, ready_to_ship_total: 2 })) : pages,
    size,
    isValidating: false,
    setSize: async value => {
      setSizeCalls.push(value);
      if (ready) readyToShipSize = value;
      else if (branded) brandedSize = value;
      else stockSize = value;
    },
  };
}
function jsx(type, props) { return { type, props: props || {} }; }
const noop = () => null;
const testModule = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "react") return {};
  if (name === "react/jsx-runtime") return { jsx, jsxs: jsx, Fragment: "fragment" };
  if (name === "swr") return Object.assign(noop, { useSWRInfinite });
  if (name === "next/link") return noop;
  if (name === "@/lib/api") return { fetcher: async () => ({}) };
  if (name === "@/lib/i18n") return { useT: () => ({ lang: "en", t: key => key }) };
  if (name === "@/lib/orderRef") return { formatOrderReference: value => String(value) };
  if (name === "@/components/PageHeader") return { default: noop };
  if (name === "@/components/StocktakeLink") return { default: noop };
  if (name === "@/components/ShipmentItemLines") return { default: noop };
  if (name === "@/components/StagePipeline") return { statusLabel: value => value };
  throw new Error(`Unexpected dependency: ${name}`);
}, testModule.exports, testModule);
const Page = testModule.exports.default;
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
function render() { return Page(); }

let tree = render();
assert.equal(stockPages[0].length, 500);
const buttons = walk(tree, node => node.type === "button" && (
  containsText(node.props.children, "Load more") || containsText(node.props.children, "common.loadMore")
));
assert.equal(buttons.length, 3, "all three finished-goods lists expose load-more while another page exists");
await buttons[0].props.onClick();
await buttons[1].props.onClick();
await buttons[2].props.onClick();
assert.deepEqual(setSizeCalls, [2, 2, 2], "each load-more button advances only its own list");
tree = render();
assert(containsText(tree, "A") && containsText(tree, "B"), "stock pages aggregate into one table");
assert(containsText(tree, "X") && containsText(tree, "Y"), "branded pages aggregate into one table");
assert(containsText(tree, "SO-9") && containsText(tree, "SO-10"), "reservation-backed orders aggregate across bounded inbox pages");
console.log("PASS: Finished Goods stock, branded, and reservation-backed order pages load more and aggregate.");
