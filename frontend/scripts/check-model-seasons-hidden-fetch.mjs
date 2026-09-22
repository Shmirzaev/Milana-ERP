import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("../src/app/(app)/models/[id]/page.tsx", import.meta.url), "utf8");

// This mirrors the component's actual edit gate: the seasons selector is only
// rendered for a new/edit model, so its SWR key must be null in read-only mode.
assert.match(source, /const isEditable = isNewModel \|\| searchParams\.get\("mode"\) === "edit";/);
assert.match(source, /useSWR<string\[\]>\(isEditable \? "\/api\/collections\/seasons" : null, fetcher\)/);

const requests = [];
const requestSeasons = key => { requests.push(key); return { data: key ? ["Winter"] : undefined }; };
const renderModel = (isEditable, currentSeason = "") => {
  const seasons = requestSeasons(isEditable ? "/api/collections/seasons" : null).data || [];
  const options = [currentSeason, ...seasons.filter(season => season !== currentSeason)].filter(Boolean);
  return options.map(season => `<option>${season}</option>`).join("");
};

assert.match(renderModel(false, "Summer"), /Summer/, "read-only view must retain its saved season");
assert.deepEqual(requests, [null]);
requests.length = 0;
assert.match(renderModel(true), /Winter/, "edit model form must render fetched season options");
assert.deepEqual(requests, ["/api/collections/seasons"]);

console.log("Model detail: seasons fetch only occurs for the visible edit/new-model form.");
