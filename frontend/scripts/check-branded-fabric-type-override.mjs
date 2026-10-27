import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const planningPage = readFileSync(new URL("../src/app/(app)/planning/page.tsx", import.meta.url), "utf8");

assert.doesNotMatch(planningPage, /matches this model's fabric type/);
assert.match(
  planningPage,
  /if \(!materials\.length \|\| materials\.some\(\(row\) => !row\.batch\)\) \{\s*setBrandedErr\(t\("page\.planning\.selectEveryFabric"\)\)/,
);
assert.match(planningPage, /fabricBatchOptions\(availableFabricBatches, selectedBrandedFabricItemIds, true\)/);
assert.match(planningPage, /\|\| availableFabricBatches\[0\]/);
assert.match(planningPage, /Number\(batch\.available_quantity \|\| 0\) > 0/);
assert.match(planningPage, /!\["failed", "rejected"\]\.includes\(String\(batch\.qc_status \|\| ""\)\.toLowerCase\(\)\)/);

console.log("Branded-stock fabric type override contract passed.");
