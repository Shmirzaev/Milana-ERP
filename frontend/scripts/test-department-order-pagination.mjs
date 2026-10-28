import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/departments/[code]/page.tsx", import.meta.url), "utf8");

assert.match(page, /useSWRInfinite<DepartmentOrderPage>/, "core department orders should use bounded pages");
assert.match(page, /\/api\/inbox\/department-orders\?dept=\$\{code\}.*limit=50&offset=\$\{index \* 50\}/, "core pages should carry department, timezone and 50-row offset");
assert.match(page, /include_core_orders=false/, "the compatibility inbox should skip the duplicate core graph");
assert.match(page, /departmentOrderPages\?\.flatMap/, "the list should combine requested pages only");
assert.match(page, /queueKind: row\.queue_kind/, "server queue identity should be rendered by the existing component");
assert.match(page, /departmentOrderPages\?\.\[0\]\?\.total/, "the heading should use the exact server total");
assert.match(page, /departmentOrdersHasMore/, "the screen should expose a load-more action");
assert.match(page, /mutateDepartmentOrderPages\(\)/, "work-order actions should refresh the paged list");
assert.doesNotMatch(page, /mergeDepartmentOrders\(/, "the screen should not merge capped compatibility arrays");

console.log("PASS: department core inbox uses bounded canonical pages.");
