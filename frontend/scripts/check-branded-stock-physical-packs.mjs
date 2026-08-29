import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(
  new URL("../src/app/(app)/sales-orders/new/page.tsx", import.meta.url),
  "utf8",
);

assert.match(
  page,
  /const \[includePartialPacks, setIncludePartialPacks\] = useState\(true\);/,
  "Every available physical package must be visible by default.",
);
assert.match(
  page,
  /const fullQty = fullQuantities\.reduce\(\(sum, qty\) => sum \+ qty, 0\);/,
  "Full packages must contribute their actual available quantity to the stock summary.",
);
assert.match(
  page,
  /option\.fullQuantities\.slice\(0, fullPackCount\)\.reduce\(\(sum, qty\) => sum \+ qty, 0\)/,
  "Selected physical packages must use their actual quantities instead of a fixed 60 pieces.",
);
assert.doesNotMatch(
  page,
  /const saleableQty = \(fullPacks \* effectivePackPieces\)/,
  "Stock totals must not truncate over-capacity legacy packages.",
);

const quantities = [120, 60, 45];
const standard = 60;
const fullQuantities = quantities.filter((qty) => qty >= standard).sort((a, b) => b - a);
const partialQuantities = quantities.filter((qty) => qty > 0 && qty < standard).sort((a, b) => b - a);

assert.equal(fullQuantities.length + partialQuantities.length, 3);
assert.equal([...fullQuantities, ...partialQuantities].reduce((sum, qty) => sum + qty, 0), 225);
assert.equal(fullQuantities.slice(0, 1).reduce((sum, qty) => sum + qty, 0), 120);

console.log("Branded-stock physical package contract passed.");
