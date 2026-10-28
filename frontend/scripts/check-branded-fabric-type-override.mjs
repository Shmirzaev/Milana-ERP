import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const planningPage = readFileSync(new URL("../src/app/(app)/planning/page.tsx", import.meta.url), "utf8");
const qcModule = readFileSync(new URL("../src/lib/inventoryQcStatus.ts", import.meta.url), "utf8");

assert.doesNotMatch(planningPage, /matches this model's fabric type/);
assert.match(
  planningPage,
  /if \(!materials\.length \|\| materials\.some\(\(row\) => !row\.batch\)\) \{\s*setBrandedErr\(t\("page\.planning\.selectEveryFabric"\)\)/,
);
assert.match(planningPage, /fabricBatchOptions\(availableFabricBatches, selectedBrandedFabricItemIds, true\)/);
assert.match(planningPage, /\|\| availableFabricBatches\[0\]/);
assert.match(planningPage, /Number\(batch\.available_quantity \|\| 0\) > 0/);
// Execute the real canonical enum and this screen's actual memo instead of
// requiring the pre-refactor string spelling. Unknown QC retains legacy access.
function declaration(file, name) {
  const matches = [];
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(file) === name) matches.push(node);
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.equal(matches.length, 1, `Locate exactly one real ${name} declaration`);
  return matches[0];
}

function evaluateAvailability(source, batches) {
  const file = ts.createSourceFile("planning.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const canonicalImport = file.statements.find(node => ts.isImportDeclaration(node)
    && node.moduleSpecifier.text === "@/lib/inventoryQcStatus");
  const imports = canonicalImport?.importClause?.namedBindings;
  assert.ok(imports && ts.isNamedImports(imports), "Planning must use the canonical QC module");
  for (const name of ["InventoryQcStatus", "inventoryQcStatus"]) {
    assert.ok(imports.elements.some(entry => entry.name.text === name && !entry.propertyName), `Import canonical ${name}`);
  }
  const excluded = declaration(file, "PLANNING_EXCLUDED_QC_STATUSES");
  const available = declaration(file, "availableFabricBatches");
  const compile = text => ts.transpileModule(text, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const vocabulary = {};
  new Function("exports", compile(qcModule))(vocabulary);
  const output = {};
  new Function("exports", "useMemo", "fabricBatches", "InventoryQcStatus", "inventoryQcStatus",
    compile(`const ${excluded.getText(file)}; export const rows = ${available.initializer.getText(file)};`))(
    output, compute => compute(), batches, vocabulary.InventoryQcStatus, vocabulary.inventoryQcStatus,
  );
  return output.rows.map(row => row.id);
}

const cases = [
  ["failed", 2, false], ["rejected", 2, false], ["FAILED", 2, false], ["ReJeCtEd", 2, false],
  ["pending", 2, true], ["passed", 2, true], ["hold", 2, true],
  ["", 2, true], [null, 2, true], [undefined, 2, true], ["legacy", 2, true],
  [" failed ", 2, true], // Legacy lower-cases but does not trim.
  ["passed", 0, false], ["passed", -1, false], ["passed", undefined, false], ["passed", "3", true],
];
const batches = cases.map(([qc_status, available_quantity], id) => ({ id, qc_status, available_quantity }));
const expected = cases.flatMap(([, , allowed], id) => allowed ? [id] : []);
const verifyQc = source => assert.deepEqual(evaluateAvailability(source, batches), expected,
  "Planning must retain positive stock and exclude exactly failed/rejected QC, including mixed case");
verifyQc(planningPage);

// Every mutation changes only an in-memory source copy; no application file is edited.
for (const [name, before, after] of [
  ["QC guard removed", "return status === null || !PLANNING_EXCLUDED_QC_STATUSES.includes(status);", "return true;"],
  ["failed member replaced", "InventoryQcStatus.FAILED,", "InventoryQcStatus.HOLD,"],
  ["rejected member replaced", "InventoryQcStatus.REJECTED,", "InventoryQcStatus.PENDING,"],
  ["unknown QC refused", "return status === null ||", "return status !== null &&"],
]) {
  const mutated = planningPage.replace(before, after);
  assert.notEqual(mutated, planningPage, `Mutation must apply: ${name}`);
  assert.throws(() => verifyQc(mutated), /Planning must retain positive stock/, `Reject mutation: ${name}`);
}

console.log("Branded-stock fabric type override contract passed; 16 QC/quantity cases and 4 deliberate faults passed.");
