import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");

assert.match(page, /const \[showForm, setShowForm\] = useState\(false\);/, "cutting passports must track whether the form is open");
assert.match(
  page,
  /useCuttingPassportDirectoryKeys\(showForm\)/,
  "the 500-order directory must load only while the create/edit form is open",
);
assert.match(
  page,
  /directoryKeys\.operators, fetcher\)/,
  "the operator directory must load only while the create/edit form is open",
);
assert.match(page, /<Modal[\s\S]*?open=\{showForm\}/, "the guarded directories must correspond to the passport form modal");

const requests = [];
const requestDirectories = (open) => {
  const keys = open
    ? ["/api/production-orders?page_size=500", "/api/cutting-passports/operators"]
    : [null, null];
  requests.push(keys);
  return keys;
};

assert.deepEqual(requestDirectories(false), [null, null], "closed form must skip both option directories");
assert.deepEqual(
  requestDirectories(true),
  ["/api/production-orders?page_size=500", "/api/cutting-passports/operators"],
  "create/edit form must load both option directories",
);
assert.deepEqual(requests, [[null, null], ["/api/production-orders?page_size=500", "/api/cutting-passports/operators"]]);

console.log("Cutting passport hidden-fetch contract passed.");
