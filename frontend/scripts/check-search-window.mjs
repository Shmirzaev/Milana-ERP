import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/search/page.tsx", "utf8");
const inventory = fs.readFileSync("src/app/(app)/inventory/page.tsx", "utf8");

assert.match(page, /const INITIAL_RESULTS_PER_TYPE = 30;/, "Global search must mount a bounded initial result window.");
assert.match(page, /\.slice\(0, visibleCounts\[type\]\)\.map/, "Each result family must render only its current window.");
assert.match(page, /Math\.min\(current\[type\] \+ INITIAL_RESULTS_PER_TYPE, grouped\[type\]\.length\)/, "Load more must retain access to every fetched result.");
assert.match(page, /t\("common\.loadMore"\)/, "The incremental control must remain localized.");
assert.match(inventory, /const INVENTORY_RENDER_PAGE_SIZE = 80;/, "Inventory must mount a bounded initial batch-row window.");
assert.match(inventory, /inventoryRows\.slice\(0, inventoryRenderLimit\)/, "Inventory rendering must use the current window.");
assert.equal((inventory.match(/visibleInventoryRows\.map/g) || []).length, 2, "Desktop and mobile Inventory layouts must share the bounded window.");
assert.match(inventory, /Math\.min\(current \+ INVENTORY_RENDER_PAGE_SIZE, inventoryRows\.length\)/, "Inventory Load more must retain access to every fetched row.");
assert.match(inventory, /const searchTimerRef = useRef<number \| null>\(null\);/, "Inventory must retain the pending type-to-search timer.");
assert.match(inventory, /window\.clearTimeout\(searchTimerRef\.current\);/, "Explicit Inventory search must cancel its pending automatic navigation.");

console.log("Bounded global and inventory search rendering contract passed.");
