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
assert.match(planningPage, /fabricBatchOptions\(brandedFabricBatches, selectedBrandedFabricItemIds, true\)/);
assert.match(planningPage, /\|\| brandedFabricBatches\[0\]/);
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

// Execute the real department selectors, option builder and default-selection
// effect. Fabric type prioritizes choices but must never remove a valid source
// or replace an operator's deliberately selected non-BOM fabric.
function verifyDepartmentSources(source) {
  const file = ts.createSourceFile("planning.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const helpers = [], names = new Set(["fmtQty", "fabricBatchLabel", "fabricBatchOptions"]);
  let effect;
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && names.has(node.name?.text)) helpers.push(node.getText(file));
    if (ts.isCallExpression(node) && node.expression.getText(file) === "useEffect" &&
        node.getText(file).includes("const firstMaterial = brandedForm.materials[0]")) effect = node.arguments[0].getText(file);
    ts.forEachChild(node, visit);
  }
  visit(file);
  assert.ok(effect, "Use the actual branded source default effect");
  const compile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const text = [...helpers,
    ...["fabricsForCutting", "brandedFabricBatches", "brandedFabricBatchOptions"].map(name => `const ${declaration(file, name).getText(file)};`),
    `exports.rows = brandedFabricBatches; exports.options = brandedFabricBatchOptions; exports.client = fabricsForCutting; exports.apply = ${effect};`,
  ].join("\n");
  const batch = (id, item_id) => ({ id, item_id, batch_no: `LOT-${id}`, item_name: `Fabric-${item_id}`,
    available_quantity: 10, unit: "kg", image_url: `/images/${id}.png` });
  const central = [batch(11, 1), batch(12, 2)], eco = [batch(-21, 3), batch(22, 4)];
  for (const matchingIds of [[1, 3], []]) {
   for (const [department, rows] of [["CUT", central], ["ECT", eco]]) {
    const state = { model_id: 1, cutting_department_code: department, materials: [{ fabric_batch_id: rows[1].id }] };
    const output = {};
    new Function("exports", "useMemo", "availableFabricBatches", "ecoFabricBatches", "brandedForm", "selectedBrandedFabricItemIds",
      "numberOrZero", "DEFAULT_MATERIAL_UNIT", "setBrandedForm", compile(text))(
      output, compute => compute(), central, eco, state, matchingIds, value => Number(value || 0), "kg",
      change => Object.assign(state, change(state)),
    );
    assert.deepEqual(output.rows.map(row => row.id), rows.map(row => row.id), "Branded choices must use the selected Cutting department's stock");
    assert.deepEqual(output.client("CUT").map(row => row.id), [11, 12], "Client CUT must retain central stock");
    assert.deepEqual(output.client("ECT").map(row => row.id), [-21, 22], "Client ECT must use ECO stock");
    assert.deepEqual(output.options.map(option => option.value), rows.map(row => row.id), "Nonmatching fabric types remain valid choices");
    assert.deepEqual(output.options.map(option => option.imageUrl), rows.map(row => row.image_url));
    output.apply();
    assert.equal(state.materials[0].fabric_batch_id, rows[1].id, "A deliberate available non-BOM source must stay selected");
    state.materials = [{ fabric_batch_id: 0 }];
    output.apply();
    assert.equal(state.materials[0].fabric_batch_id, rows[0].id, "An unselected source defaults within the chosen department");
   }
  }
}
verifyDepartmentSources(planningPage);
const wrongFactory = planningPage.replace('const brandedFabricBatches = brandedForm.cutting_department_code === "ECT" ? ecoFabricBatches : availableFabricBatches;',
  "const brandedFabricBatches = availableFabricBatches;");
assert.notEqual(wrongFactory, planningPage);
assert.throws(() => verifyDepartmentSources(wrongFactory), /selected Cutting department's stock/, "Reject accidental central-only branded sourcing");

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

console.log("Branded-stock fabric override passed: CUT/ECT client/branded source execution, non-BOM choice retention, pictures, 16 QC/quantity cases and deliberate factory/QC faults.");
