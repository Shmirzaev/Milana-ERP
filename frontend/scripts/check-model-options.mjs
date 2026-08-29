import assert from "node:assert/strict";
import fs from "node:fs";

const hook = fs.readFileSync("src/lib/useModelOptions.ts", "utf8");
const selector = fs.readFileSync("src/components/ModelAsyncSelect.tsx", "utf8");
const searchable = fs.readFileSync("src/components/SearchableSelect.tsx", "utf8");
const planning = fs.readFileSync("src/app/(app)/planning/page.tsx", "utf8");
const cutting = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");
const modelDetail = fs.readFileSync("src/app/(app)/models/[id]/page.tsx", "utf8");
const productionDetail = fs.readFileSync("src/app/(app)/production-orders/[id]/page.tsx", "utf8");
const newSalesOrder = fs.readFileSync("src/app/(app)/sales-orders/new/page.tsx", "utf8");

assert.match(hook, /const PAGE_SIZE = 30;/, "Model selector pages must request 30 rows.");
assert.match(hook, /const SEARCH_DEBOUNCE_MS = 180;/, "Model search must stay responsive without firing on every keystroke.");
assert.match(hook, /controller\.abort\(\)/, "Superseded model-option requests must be cancelled.");
assert.match(hook, /previous && !previous\.has_more/, "Pagination must stop when the API reports no next page.");
assert.match(hook, /new Map<number, ModelOption>/, "Options from multiple pages must be deduplicated by id.");
assert.match(hook, /\/api\/model-options\?/, "The shared hook must use the compact endpoint.");
assert.match(hook, /ids=\$\{encodeURIComponent/, "The selected model label must be recovered by id.");
assert.match(hook, /offset \+= 50/, "Exact-id label hydration must split requests into bounded chunks.");
assert.match(hook, /params\.append\("ids"/, "Exact-id hydration must use the compact ids lookup.");
assert.match(selector, /serverFilter/, "The shared select must use server-side filtering.");
assert.match(searchable, /onSearchChange\?\./, "Typed searches must be forwarded to the server hook.");
assert.match(searchable, /onLoadMore\?\./, "The selector must support bounded incremental loading.");
assert.match(searchable, /const LOCAL_RENDER_PAGE_SIZE = 80;/, "Local selectors must not mount an unbounded option list.");
assert.match(searchable, /searchKey: normalizeModelSearch/, "Local selector search text must be normalized once per option set.");
assert.match(searchable, /visibleOptions\.map/, "Only the current local option window may be rendered.");
assert.match(planning, /<ModelAsyncSelect[\s\S]*status="approved"/, "Planning must use the approved-model async selector.");
assert.match(productionDetail, /<ModelAsyncSelect/, "Production-order editing must use the shared async selector.");
assert.match(newSalesOrder, /<ModelAsyncSelect/, "New client orders must use the shared async selector.");
assert.doesNotMatch(planning, /\/api\/models\?status=approved/, "Planning must not load every approved model.");
assert.doesNotMatch(cutting, /\/api\/models\?page_size=500/, "Cutting passports must not load 500 full models.");
assert.match(modelDetail, /variants\?page=\$\{pageIndex \+ 1\}&page_size=50/, "Variants must use explicit bounded pages.");

console.log("Bounded model selector contract passed.");
