import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/departments/[code]/page.tsx", import.meta.url), "utf8");
const finishedGoodsPage = fs.readFileSync(new URL("../src/app/(app)/finished-goods/page.tsx", import.meta.url), "utf8");

assert.match(page, /useSWRInfinite<InboxPackagePage>/, "FGS package lists should fetch bounded pages");
assert.match(page, /status=pending&page=\$\{index \+ 1\}&page_size=50/, "pending packages need explicit 50-row pages");
assert.match(page, /status=ready&page=\$\{index \+ 1\}&page_size=50/, "ready packages need explicit 50-row pages");
assert.match(page, /pendingPackagePages\?\.flatMap/, "pending pages should combine only requested rows");
assert.match(page, /readyPackagePages\?\.flatMap/, "ready pages should combine only requested rows");
assert.match(page, /readyPackagePages\?\.\[0\]\?\.group_total/, "ready order heading needs exact group count");
assert.match(page, /mutatePendingPackagePages\(\), mutateReadyPackagePages\(\)/, "shipment writes should refresh package pages");
assert.doesNotMatch(page, /include_packages=false/, "the inbox request must retain reservation-backed ready-to-ship orders");
assert.doesNotMatch(page, /data\?\.pending_packages|data\?\.ready_packages/, "the visible lists must not reuse the capped compatibility arrays");
assert.match(finishedGoodsPage, /ready_to_ship_limit=50&ready_to_ship_offset=/, "Finished Goods should page its reservation-backed order list");
assert.match(finishedGoodsPage, /ready_to_ship_total/, "Finished Goods should stop paging from the exact order total");
assert.doesNotMatch(finishedGoodsPage, /include_packages=false/, "the FGS screen must keep its reservation-backed order list enabled");

console.log("PASS: FGS package and reservation-backed order lists use bounded pages.");
