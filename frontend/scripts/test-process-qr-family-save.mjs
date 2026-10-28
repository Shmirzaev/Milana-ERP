import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

// Execute the actual page handler with controlled API/cache timing.
const source = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let handler;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === "saveOperationsToModel") handler = node.getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast);
assert.ok(handler);
const javascript = ts.transpileModule(handler, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
const operation = { id: "sew", sewingFactory: "milana", rate: "50.125", selected: true };
const hidden = { id: "besttex", sewingFactory: "besttex", rate: "75", selected: true };

function fixture({ fail = false, switchVariant = false, stale = false, eco = false } = {}) {
  const writes = [];
  const refreshed = [];
  const state = { dirty: true };
  const selectedModelIdRef = { current: 8048 };
  const context = vm.createContext({
    modelApiBase: eco ? "/api/usluga" : "/api",
    selectedModel: { id: stale ? 8051 : 8048, code: "PJ1236-V-6120" },
    selectedModelId: 8048, loadedOperationsModelId: 8048, selectedModelIdRef,
    selectedProcess: undefined, factoryOperations: [operation], operations: [operation, hidden],
    printPaidOperationFactory: "milana", serializePaidOperations: rows => structuredClone(rows),
    modelVariantOption: () => ({ modelNo: "PJ1236" }),
    t: (key, values) => JSON.stringify({ key, values }),
    setSavingModelOperations: value => { state.saving = value; },
    setModelSaveMsg: value => { state.message = value; },
    setOperations: value => { state.operations = value; },
    setLoadedOperationsModelId: value => { state.modelId = value; },
    setLoadedOperationsSignature: value => { state.signature = value; },
    setOperationModelDirty: value => { state.dirty = value; },
    api: { patch: async (path, body) => {
      writes.push({ path, body });
      if (switchVariant) selectedModelIdRef.current = 8051;
      if (fail) throw new Error("Save rejected");
    } },
    mutateModelCache: async (matches, data, options) => {
      assert.equal(data, undefined, "remove cached variant data before the next load");
      assert.equal(options.revalidate, true);
      for (const key of ["/api/models/8048", "/api/models/8051", "/api/usluga/models/8048", "/api/usluga/models/8051", "/api/models/8051/process-qr-sizes", "/api/payroll/qr-labels", null]) {
        if (matches(key)) refreshed.push(key);
      }
    },
  });
  vm.runInContext(javascript, context);
  return { run: () => context.saveOperationsToModel(), writes, refreshed, state };
}

const success = fixture();
await success.run();
assert.equal(success.writes.length, 1);
assert.equal(success.writes[0].path, "/api/models/8048/paid-operations");
assert.equal(success.writes[0].body.sewing_factory, "milana");
assert.deepEqual(success.writes[0].body.paid_operations, [operation]);
assert.deepEqual(success.refreshed, ["/api/models/8048", "/api/models/8051"]);
assert.equal(success.state.dirty, false);
assert.equal(success.state.saving, false);
assert.equal(JSON.parse(success.state.message).values.model, "PJ1236");
assert.deepEqual(success.state.operations, [operation, hidden]);

const rejected = fixture({ fail: true });
await rejected.run();
assert.deepEqual(rejected.refreshed, []);
assert.equal(rejected.state.dirty, true);
assert.equal(rejected.state.saving, false);
assert.match(rejected.state.message, /Save rejected/);

const ecoSave = fixture({ eco: true });
await ecoSave.run();
assert.equal(ecoSave.writes[0].path, "/api/usluga/models/8048/paid-operations");
assert.deepEqual(ecoSave.refreshed, ["/api/usluga/models/8048", "/api/usluga/models/8051"]);

for (const fail of [false, true]) {
  const switched = fixture({ switchVariant: true, fail });
  await switched.run();
  assert.equal(switched.state.modelId, undefined, "late response cannot switch the visible variant back");
  assert.equal(switched.state.operations, undefined, "late response cannot overwrite the new variant's operations");
  assert.equal(switched.state.dirty, true);
  assert.equal(switched.state.message, "");
}
const stale = fixture({ stale: true });
await stale.run();
assert.equal(stale.writes.length, 0, "loading a variant must never save another variant's cached operations");
console.log("Process QR family-save payload, cache refresh, error and late-response checks passed.");
