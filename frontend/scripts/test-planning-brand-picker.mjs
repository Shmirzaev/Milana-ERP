import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync(new URL("../src/app/(app)/planning/page.tsx", import.meta.url), "utf8");
const route = fs.readFileSync(new URL("../../backend/app/api/routes/catalog.py", import.meta.url), "utf8");
assert.doesNotMatch(page, /useSWR<Brand\[\]>\("\/api\/brands"/,
  "Planning must not fetch the capped 500-brand array");
assert.equal((page.match(/<BrandAsyncSelect/g) || []).length, 3,
  "all three Planning brand selectors must search bounded pages");
assert.equal((page.match(/activeOnly\s+required/g) || []).length, 3,
  "Planning choices must remain restricted to active brands");
assert.equal((page.match(/selectedBrand=\{createdBrand\}/g) || []).length, 3,
  "a new brand must remain selected immediately in any Planning form");
assert.match(page, /setCreatedBrand\(created\)/);
assert.match(page, /brandedForm\.brand_id && createdBrand\?\.id !== brandedForm\.brand_id \? `\/api\/brands\/\$\{brandedForm\.brand_id\}`/,
  "the review card must resolve an off-page selected brand name");
assert.match(route, /if active_only:\s+ordered_query = ordered_query\.filter\(Brand\.is_active\.is_\(True\)\)/,
  "the server must filter inactive brands before counting and paging");
console.log("PASS: Planning brand forms use active 50-row pages and retain off-page and newly created selections.");
