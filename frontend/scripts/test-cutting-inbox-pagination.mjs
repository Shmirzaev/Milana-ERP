import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/departments/[code]/page.tsx", import.meta.url), "utf8");
const list = fs.readFileSync(new URL("../src/components/CuttingOrderList.tsx", import.meta.url), "utf8");

assert.match(page, /&include_core_orders=false/, "compatibility inbox should skip the cutting work-order graph");
assert.match(page, /useSWRInfinite<CuttingOrderPage>/, "CUT and ECT should request bounded cutting pages");
assert.match(page, /\/api\/inbox\/cutting-orders\?dept=\$\{code\}&limit=50&offset=\$\{index \* 50\}/);
assert.match(page, /cuttingOrderPages\?\.flatMap/, "only requested cutting rows should be rendered");
assert.match(page, /cuttingOrderPages\?\.\[0\]\?\.total/, "heading should use the exact total");
assert.match(page, /cuttingOrdersHasMore/, "remaining pages need a visible action");
assert.match(page, /setCuttingOrderPageCount\(\(size\) => size \+ 1\)/);
assert.match(page, /mutateCuttingOrderPages\(\)/, "start action should refresh cutting pages");
assert.match(list, /total \?\? rows\.length/, "cutting heading should show exact total");
assert.doesNotMatch(page, /data\?\.cutting_work_orders/, "screen must not consume the capped legacy array");

console.log("PASS: CUT and ECT inboxes request exact-total 50-row cutting pages.");
