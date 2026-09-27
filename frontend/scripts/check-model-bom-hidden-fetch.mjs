import assert from "node:assert/strict";
import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/models/[id]/page.tsx", "utf8");

assert.match(page, /const \[tab, setTab\] = useState\(1\);/, "model detail must track the active tab before deriving option fetch keys");
assert.match(
  page,
  /useSWR<any\[\]>\(tab === 3 \? `\$\{modelApiBase\}\/bom-items` : null, fetcher\)/,
  "the BOM item directory must load only while its tab is visible",
);
assert.match(page, /const accessoryItems = useMemo\(\(\) => \{[\s\S]*?\(items \|\| \[\]\)/, "accessory options must tolerate the deferred directory");
assert.match(page, /{tab === 3 && \(/, "the guarded directory must correspond to the BOM tab");

const requests = [];
const requestItems = (tab) => { const key = tab === 3 ? "/api/models/bom-items" : null; requests.push(key); return key; };
assert.equal(requestItems(1), null, "hidden BOM tab must skip its directory");
assert.equal(requestItems(3), "/api/models/bom-items", "visible read/edit BOM tab must load display metadata");
assert.deepEqual(requests, [null, "/api/models/bom-items"]);

console.log("Model BOM hidden-fetch contract passed.");
