import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/departments/[code]/page.tsx", import.meta.url), "utf8");

assert.match(page, /code === "FGS" \? "&ready_to_ship_limit=50&ready_to_ship_offset=0"/, "FGS compatibility inbox should request only the first 50 ready-to-ship orders");
assert.match(page, /useSWRInfinite<any>\([\s\S]*?index === 0\) return inboxUrl/, "the paged list should reuse the compatibility response as page one");
assert.match(page, /ready_to_ship_limit=50&ready_to_ship_offset=\$\{index \* 50\}&include_core_orders=false/, "later ready-to-ship pages should use exact 50-row offsets and skip the core graph");
assert.match(page, /index \* 50 >= Number\(previous\.ready_to_ship_total/, "paging should stop at the exact ready-to-ship total");
assert.match(page, /readyToShipPages\?\.flatMap\(\(page\) => page\?\.ready_to_ship/, "the table should aggregate only loaded ready-to-ship pages");
assert.match(page, /readyToShipPages\?\.\[0\]\?\.ready_to_ship_total/, "the visible count should use the exact server total");
assert.match(page, /readyToShipRows\.length < readyToShipTotal/, "Load more should appear only while rows remain");
assert.match(page, /onClick=\{\(\) => setReadyToShipSize\(readyToShipSize \+ 1\)\}/, "Load more should fetch the next ready-to-ship page");
assert.match(page, /if \(code !== "FGS"\) return null/, "other departments should not request FGS ready-to-ship pages");
assert.match(page, /useSWRInfinite<DepartmentOrderPage>/, "existing department-order paging should remain active");
assert.match(page, /limit=50&offset=\$\{index \* 50\}/, "core department-order paging should retain its 50-row offsets");
assert.match(page, /readyPackagePages\?\.\[readyPackagePages\.length - 1\]\?\.has_more/, "the ready-package fallback should retain its own pagination");
assert.match(page, /readyPackagesByOrder\.map/, "the existing package grouping widget should remain available");
assert.match(page, /mutateReadyToShipPages\(\)/, "shipment creation should refresh the paged ready-to-ship list");

console.log("PASS: FGS department ready-to-ship uses bounded 50-row pages and preserves package and department-order widgets.");
