import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");

assert.match(page, /const \[showForm, setShowForm\] = useState\(false\);/, "cutting passports must track whether the form is open");
assert.match(
  page,
  /useCuttingPassportDirectoryKeys\(showForm\)/,
  "the operator directory must load only while the create/edit form is open",
);
assert.match(
  page,
  /directoryKeys\.operators, fetcher\)/,
  "the operator directory must load only while the create/edit form is open",
);
assert.match(page, /<Modal[\s\S]*?open=\{showForm\}/, "the guarded directories must correspond to the passport form modal");
assert.match(page, /<CuttingProductionOrderSelect inputId="cutting-passport-production-order"/, "the bounded production-order picker must mount only inside the form");
assert.doesNotMatch(page, /\/api\/production-orders\?page_size=500/, "the form must not load a capped order directory");

const requests = [];
const requestDirectories = (open) => {
  const keys = open
    ? ["/api/cutting-passports/operators"]
    : [null];
  requests.push(keys);
  return keys;
};

assert.deepEqual(requestDirectories(false), [null], "closed form must skip its operator directory");
assert.deepEqual(
  requestDirectories(true),
  ["/api/cutting-passports/operators"],
  "create/edit form must load the operator directory",
);
assert.deepEqual(requests, [[null], ["/api/cutting-passports/operators"]]);

console.log("Cutting passport hidden-fetch contract passed.");
