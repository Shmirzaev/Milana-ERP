import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync("src/lib/modelPaidOperations.ts", "utf8");
const javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { materializeLegacyPaidOperations, paidOperationsFromDetails, serializePaidOperations } =
  await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
const page = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const calls = [...page.matchAll(/materializeLegacyPaidOperations\(paidOperationsFromDetails\(selectedModel.details_json\), \[accountPaidOperationFactory\]\)/g)];
assert.equal(calls.length, 3, "automatic load, explicit reload and inference must use the session factory");
assert.ok(page.includes('<th scope="col" className="w-12">№</th>'));
assert.ok(page.includes('<td className="tabular-nums">{operationIndex + 1}</td>'));

for (const factory of ["milana", "besttex", "eco_cotton"]) {
  const load = (details) => serializePaidOperations(
    materializeLegacyPaidOperations(paidOperationsFromDetails(details), [factory]),
  );
  for (const details of [{}, { paid_operations: null }, { paidOperations: null }]) {
    const defaults = load(details);
    assert.equal(defaults.length, 5);
    assert.ok(defaults.every((row) => row.sewingFactory === factory), "hidden default factories must never enter Payroll's save payload");
  }
  assert.deepEqual(load({ paid_operations: [] }), [], "an explicitly empty list stays empty");
  const legacy = { id: "legacy", code: "LEGACY", name: "Legacy operation", rate: "210" };
  const migrated = load({ paid_operations: [legacy] });
  assert.equal(migrated.length, 1);
  assert.equal(migrated[0].sewingFactory, factory);
  assert.equal(migrated[0].legacySourceId, "legacy");
  assert.equal(migrated[0].rate, "210");
  assert.deepEqual(load({ paid_operations: migrated }), migrated, "save/reload must preserve operation identity and rate");

  const allFactories = ["milana", "besttex", "eco_cotton"].map((sewingFactory) => ({
    ...legacy, id: `configured-${sewingFactory}`, sewingFactory,
  }));
  assert.equal(load({ paid_operations: allFactories }).length, 3, "admin reads must retain configured hidden factories for the full-list save endpoint");
}
console.log("Process QR factory loading, save round-trip, and row numbering checks passed.");
