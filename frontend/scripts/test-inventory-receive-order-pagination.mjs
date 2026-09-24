import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/inventory/receive/page.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../../backend/app/api/routes/production.py", import.meta.url), "utf8");
const backendTest = fs.readFileSync(new URL("../../backend/app/tests/test_production_order_pagination.py", import.meta.url), "utf8");

assert.match(page, /useSWRInfinite<ProductionOrderPage>/, "accessory receiving should load production-order choices as pages");
assert.match(page, /page=\$\{index \+ 1\}&page_size=50&include_total=true&q=/, "the picker must request bounded, searched, exact-total pages");
assert.match(page, /previousPage && !previousPage\.has_more/, "paging should stop at the exact filtered end");
assert.match(page, /productionOrderPages\?\.flatMap\(\(page\) => page\.rows\)/, "only loaded production orders should be available to render");
assert.match(page, /hasMore=\{hasMoreProductionOrders\}/, "the picker should expose Load more while results remain");
assert.match(page, /onLoadMore=\{\(\) => void setProductionOrderPageCount\(\(size\) => size \+ 1\)\}/, "Load more should request exactly one next page");
assert.match(page, /loadMoreText=\{`\$\{t\("common\.loadMore"\)\} \(\$\{productionOrders\.length\} \/ \$\{productionOrderTotal\}\)`\}/, "Load more should show loaded rows against the exact total");
assert.match(page, /setSelectedProductionOrder\(order\)/, "the selected order must remain available when it is not in the current search page");
assert.match(page, /selectedProductionOrder \|\| issuePlanOrder/, "deep-linked selections should also remain visible after their detail loads");
assert.match(page, /onSearchChange=\{setProductionOrderSearchInput\}/, "typing should drive server-side filtering");
assert.doesNotMatch(page, /\/api\/production-orders\?page_size=500/, "the screen must not fetch the capped legacy array");
assert.match(route, /@router\.get\("\/production-orders"[\s\S]*?Depends\(require_permissions\(\*PRODUCTION_READ_PERMISSIONS\)\)[\s\S]*?include_total: bool = False/, "the paged picker must reuse the existing protected endpoint");
assert.match(backendTest, /@pytest\.mark\.parametrize\("order_count", \[1, 50, 401\]\)/, "existing backend tests exercise small, page-sized and multi-page sets");
assert.match(backendTest, /include_total=True,[\s\S]*?q=search_marker\.lower\(\)/, "existing backend tests cover filtered exact totals");

console.log("PASS: accessory receiving uses searchable 50-row production-order pages, exact totals, Load more, and selected-order recovery.");
