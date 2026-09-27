import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync(new URL("../src/lib/usePriceRequests.ts", import.meta.url), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
}).outputText;

const pages = [
  { items: [{ id: 1 }, { id: 2 }], total: 3, page: 1, page_size: 2, has_more: true },
  { items: [{ id: 3 }], total: 3, page: 2, page_size: 2, has_more: false },
];
let size = 1;
const keyFactories = [];
let swrConfig;
let setSizeCalls = [];

function useSWRInfinite(keyFactory, _fetcher, config) {
  keyFactories.push(keyFactory);
  swrConfig = config;
  return {
    data: pages.slice(0, size),
    error: undefined,
    isLoading: false,
    isValidating: false,
    setSize(value) {
      const next = typeof value === "function" ? value(size) : value;
      setSizeCalls.push(next);
      size = next;
    },
  };
}

const module = { exports: {} };
new Function("require", "exports", "module", output)(name => {
  if (name === "swr/infinite") return { default: useSWRInfinite };
  if (name === "@/lib/api") return { fetcher: async () => ({}) };
  if (name === "@/lib/priceCalculationRequests") return {};
  throw new Error(`Unexpected dependency: ${name}`);
}, module.exports, module);

const usePriceRequests = module.exports.usePriceRequests;
let result = usePriceRequests();
assert.equal(keyFactories.at(-1)(0, null), "/api/price-calculation/requests?page=1&page_size=100");
assert.equal(keyFactories.at(-1)(1, pages[0]), "/api/price-calculation/requests?page=2&page_size=100");
assert.equal(keyFactories.at(-1)(1, pages[1]), null, "completed page must stop further requests");
assert.deepEqual(result.requests.map(row => row.id), [1, 2], "first page is exposed without duplication");
assert.equal(result.hasMore, true);
assert.equal(swrConfig.refreshInterval, 15_000);
assert.equal(swrConfig.refreshWhenHidden, false);
assert.equal(swrConfig.refreshWhenOffline, false);

result.loadMore();
assert.deepEqual(setSizeCalls, [2], "rendered load-more action requests the next page");
result = usePriceRequests();
assert.deepEqual(result.requests.map(row => row.id), [1, 2, 3], "pages are aggregated in server order");
assert.equal(result.hasMore, false);
console.log("PASS: pricing hook executes SWR key pagination, bounded page size, aggregation, load-more, and hidden/offline polling guards.");
