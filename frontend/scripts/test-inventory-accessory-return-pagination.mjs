import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/inventory/receive/page.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../../backend/app/api/routes/inventory.py", import.meta.url), "utf8");
const service = fs.readFileSync(new URL("../../backend/app/services/inventory.py", import.meta.url), "utf8");
const backendTest = fs.readFileSync(new URL("../../backend/app/tests/test_accessory_return_balance.py", import.meta.url), "utf8");

assert.match(page, /useSWRInfinite<AccessoryIssueSummaryPage>/, "accessory returns should use bounded issue-summary pages");
assert.match(page, /page=\$\{index \+ 1\}&page_size=50&include_total=true&returnable_only=true&orders_only=true&q=/, "order selection must use 50-row unique-order pages and exact filtered totals");
assert.match(page, /production_order_id=\$\{accessoryReturnSelectedOrderId\}&q=/, "item selection must be scoped to the selected production order");
assert.match(page, /accessoryReturnOrderPages\?\.flatMap\(\(page\) => page\.rows\)/, "only loaded order-summary rows should be held by the picker");
assert.match(page, /accessoryReturnItemPages\?\.flatMap\(\(page\) => page\.rows\)/, "only loaded item-summary rows should be held by the picker");
assert.match(page, /asyncOrderHasMore=\{Boolean\(accessoryReturnOrderLastPage\?\.has_more\)\}/, "order picker should expose Load more");
assert.match(page, /asyncItemHasMore=\{Boolean\(accessoryReturnItemLastPage\?\.has_more\)\}/, "item picker should expose Load more");
assert.match(page, /setSelectedAccessoryReturnOrder\(order\)/, "selected order identity should survive search/page changes");
assert.match(page, /setSelectedAccessoryReturnItem\(item\)/, "selected item identity should survive search/page changes");
assert.doesNotMatch(page, /\/api\/inventory\/accessory-issues\?page_size=500/, "Receive/Return must not fetch the old capped summary array");
assert.match(route, /returnable_only: bool = False/, "route should expose opt-in returnable-only rows");
assert.match(route, /orders_only: bool = False/, "route should expose exact unique-order paging for the order selector");
assert.match(route, /has_more": safe_page \* safe_size < total/, "route should return page state based on exact total");
assert.match(service, /if returnable_only:[\s\S]*?returnable_quantity[\s\S]*?EPSILON/, "filtering must use computed, net returnable quantities");
assert.match(backendTest, /test_return_picker_pages_exact_returnable_groups_beyond_legacy_cap/, "backend coverage must exercise more than 500 total summary groups");
assert.match(backendTest, /"total"\] == 401/, "backend coverage must assert exact filtered total");

console.log("PASS: accessory returns use separate searchable 50-row exact-total order/item pages and preserve selected identities.");
