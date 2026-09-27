import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/finished-goods/page.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../../backend/app/api/routes/finished_goods.py", import.meta.url), "utf8");

assert.match(page, /\/api\/finished-goods\?page=\$\{index \+ 1\}&page_size=50&q=/, "stock table should start at an exact-total 50-row page");
assert.match(page, /\/api\/finished-goods\/branded-stock\?page=\$\{index \+ 1\}&page_size=50&q=/, "branded stock table should start at an exact-total 50-row page");
assert.doesNotMatch(page, /\/api\/finished-goods\?limit=500|\/api\/finished-goods\/branded-stock\?limit=500/, "screen must not fetch 500 rows per initial page");
assert.match(page, /stockPages\?\.flatMap\(\(page\) => page\.rows\)/, "stock table should flatten only requested pages");
assert.match(page, /brandedPages\?\.flatMap\(\(page\) => page\.rows\)/, "branded table should flatten only requested pages");
assert.match(page, /stockPages\?\.at\(-1\)\?\.has_more/, "stock Load more should follow the exact page contract");
assert.match(page, /brandedPages\?\.at\(-1\)\?\.has_more/, "branded Load more should follow the exact page contract");
assert.match(page, /deferredStockSearch/);
assert.match(page, /deferredBrandedSearch/);
assert.match(page, /\{data\.length\} \/ \{stockTotal\}/, "stock table should show loaded/total rows");
assert.match(page, /\{branded\.length\} \/ \{brandedTotal\}/, "branded table should show loaded/total rows");
assert.match(api, /q: Annotated\[str \| None, Query\(max_length=100\)\] = None/);
assert.match(api, /def _search_stock_rows\(/, "stock search should be filtered before exact totals and page selection");
assert.equal((api.match(/_search_stock_rows\(qry, q,/g) || []).length, 2, "both legacy-compatible stock endpoints support server-side search");
assert.match(api, /if total is None:\s+return rows/, "legacy unpaged clients retain the list response shape");

console.log("PASS: Finished Goods stock tables request exact-total 50-row pages, server search and preserve legacy API shape.");
