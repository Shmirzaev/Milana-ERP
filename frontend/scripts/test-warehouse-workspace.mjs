import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

function load(path, dependencies = {}) {
  const source = fs.readFileSync(new URL(path, import.meta.url), "utf8");
  const exports = {};
  new Function("exports", "require", ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText)(exports, name => {
    assert.ok(name in dependencies, name); return dependencies[name];
  });
  return exports;
}
const modelCode = load("../src/lib/modelCode.ts");
const { warehouseMatches } = load("../src/lib/warehouseWorkspace.ts", {"@/lib/modelCode": modelCode});
const rows = [
  {model_id: 1, model_code: "SJ4044-3372", package_no: "PK-1", storage_cell: "A-01"},
  {model_id: 2, model_code: "SJ4044-3373", package_no: "PK-3372", storage_cell: "A-01"},
  {model_id: 3, model_code: "SJ4044-33721", package_no: "PK-3", storage_cell: "A-02"},
];
assert.deepEqual(warehouseMatches(rows, "", "1"), [rows[0]], "choosing a variant cannot include its sibling or prefix variant");
assert.deepEqual(warehouseMatches(rows, "V-3372", "1"), [rows[0]], "displayed variant search intersects exact choice");
assert.deepEqual(warehouseMatches(rows, "V-3373", "1"), [], "query must not widen exact variant choice");
assert.deepEqual(warehouseMatches(rows, "PK-3372", ""), [rows[1]], "package search stays available");
assert.deepEqual(warehouseMatches(rows, "3372", ""), [rows[0], rows[2]], "model searches exclude unrelated package-number matches");
assert.deepEqual(warehouseMatches(rows, "A-01", "1"), [rows[0]], "location search intersects variant");
const large = Array.from({length: 2500}, (_, index) => ({model_id: index + 1, model_code: `QA-${index}`, package_no: `PK-${index}`}));
assert.deepEqual(warehouseMatches(large, "", "2500"), [large[2499]], "older options remain reachable beyond initial rendering limits");
console.log("Warehouse exact-variant/query/location intersection and 2,500-row lookup passed.");
