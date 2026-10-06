import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/production-orders/page.tsx", import.meta.url), "utf8");
const api = fs.readFileSync(new URL("../../backend/app/api/routes/production.py", import.meta.url), "utf8");

assert.match(page, /useSWRInfinite<ProductionOrderPage>/, "production orders should request page objects incrementally");
assert.match(page, /page=\$\{index \+ 1\}&page_size=50&include_total=true&q=/, "each page should carry the exact total and current search");
assert.match(page, /previousPage && !previousPage\.has_more/, "paging should stop at the last exact-total page");
assert.match(page, /const data = pages\?\.flatMap\(\(page\) => page\.rows\)/, "the visible table should contain only loaded pages");
assert.match(page, /\{data\.length\} \/ \{total\}/, "the screen should show loaded rows against the exact total");
assert.match(page, /setSize\(size \+ 1\)/, "Load more should advance one page");
assert.match(api, /ProductionOrder\.production_no\.ilike\(pattern, escape="\\\\"\)/, "the server search should escape SQL wildcard characters");
assert.match(api, /Model\.code\.ilike\(pattern, escape="\\\\"\)/, "the search should include model codes");

console.log("PASS: Production Orders uses escaped-search 50-row pages with exact totals and Load more.");
