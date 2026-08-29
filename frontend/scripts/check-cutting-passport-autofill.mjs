import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const pageSource = await readFile(
  new URL("../src/app/(app)/work-orders/[id]/cutting/page.tsx", import.meta.url),
  "utf8",
);
const helperSource = await readFile(
  new URL("../src/lib/cuttingPassportAutofill.ts", import.meta.url),
  "utf8",
);

assert.match(pageSource, /refreshInterval:\s*15_000/);
assert.match(pageSource, /passportAutofillDirtyFields\.current\.add\(field\)/);
assert.match(pageSource, /dirtyFields\.has\(field\)/);
assert.match(pageSource, /beika_kg:\s*passportBeikaKg \?\? ""/);
assert.match(pageSource, /setPassportAutofillField\("cut_pieces"/);
assert.match(pageSource, /setPassportAutofillField\("layup_operator_name"/);
assert.match(helperSource, /layerWeight \* totalLayers \+ scrapKg/);
assert.match(helperSource, /values\.material_rolls_used = rollsCount/);
assert.match(helperSource, /quantities\.reduce\(\(sum, quantity\) => sum \+ quantity, 0\)/);

console.log("cutting passport autofill contract passed");
