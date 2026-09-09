import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const helperSource = fs.readFileSync("src/lib/processQrLabelIdentity.ts", "utf8");
const helperJavaScript = ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const helperModuleUrl = `data:text/javascript;base64,${Buffer.from(helperJavaScript).toString("base64")}`;
const { buildOperationLabelTokens, buildIssuedOperationNumbers, correctedOperationIdentityNeedsReview } = await import(helperModuleUrl);

const dummyOperations = Array.from({ length: 20 }, (_, index) => ({
  id: `dummy-operation-${index + 1}`,
  code: "SEW-NEW",
  name: `Dummy checked process ${index + 1}`,
  sourceOrder: index + 1,
}));

const tokens = buildOperationLabelTokens(dummyOperations);
const tokenValues = dummyOperations.map((operation) => tokens.get(operation.id));

assert.equal(tokens.size, 20, "all checked dummy processes must receive a label token");
assert.equal(new Set(tokenValues).size, 20, "shared operation codes must not collapse to one label identity");
assert.equal(tokenValues[0], "SEW-NEW", "the first process must retain the historical code-only identity");
assert.ok(tokenValues.slice(1).every((token) => token?.startsWith("SEW-NEW-")), "later duplicate codes need stable discriminators");
assert.ok(tokenValues.every((token) => token && token.length <= 24), "operation tokens must fit the existing label ID budget");

const repeatedTokens = buildOperationLabelTokens(dummyOperations);
assert.deepEqual(
  dummyOperations.map((operation) => repeatedTokens.get(operation.id)),
  tokenValues,
  "dummy label identities must be stable when the same manual order reloads",
);

const uniqueOperations = dummyOperations.slice(0, 3).map((operation, index) => ({
  ...operation,
  code: `SEW-${index + 1}`,
}));
assert.deepEqual(
  uniqueOperations.map((operation) => buildOperationLabelTokens(uniqueOperations).get(operation.id)),
  ["SEW-1", "SEW-2", "SEW-3"],
  "unique existing operation codes must remain unchanged",
);

// All dummy rows above are in memory only and disappear when this process exits.
console.log("Process QR duplicate-operation label identity test passed with 20 disposable dummy processes.");

// Reproduce an edited model whose first shared code was already issued for a different process.
const incidentOperations = [
  { id: "front", code: "SEW-NEW", name: "Chontak qoyish", section: "sewing", rate: "200" },
  { id: "planka", code: "SEW-NEW", name: "planka tikish", section: "sewing", rate: "70" },
  { id: "etak-a", code: "SEW-NEW", name: "etak rashma", section: "sewing", rate: "230" },
  { id: "etak-b", code: "SEW-NEW", name: "etak rashma", section: "sewing", rate: "250" },
];
const originalTokens = buildOperationLabelTokens(incidentOperations);
const uid = (token, size) => `PY:MAN:7522:8840-1CPE3HT:${token}:MIL:SEW-09:${size}:1`;
const issued = ["XL-50", "2XL-52", "3XL-54", "4XL-56", "5XL-58", "6XL-60"].flatMap((size, sizeIndex) => [
  { id: sizeIndex * 10 + 1, label_uid: uid("SEW-NEW", size), operation_code: "SEW-NEW", operation_name: "planka tikish", operation_section: "sewing", rate_per_piece: 70, payload: "immutable" },
  ...incidentOperations.slice(1).map((operation, index) => ({
    id: sizeIndex * 10 + index + 2, label_uid: uid(originalTokens.get(operation.id), size), operation_code: operation.code,
    operation_name: operation.name, operation_section: operation.section, rate_per_piece: Number(operation.rate), payload: "immutable",
  })),
]);
const before = JSON.stringify(issued);
const repairedTokens = buildOperationLabelTokens(incidentOperations, issued);
assert.notEqual(repairedTokens.get("front"), "SEW-NEW", "No.1 needs a new identity when its old code token belongs to No.2");
assert.deepEqual(incidentOperations.slice(1).map(op => repairedTokens.get(op.id)), incidentOperations.slice(1).map(op => originalTokens.get(op.id)), "unaffected issued identities must not change");
const existingUids = new Set(issued.map(label => label.label_uid));
let missing = 0;
for (const size of ["XL-50", "2XL-52", "3XL-54", "4XL-56", "5XL-58", "6XL-60"]) {
  for (const operation of incidentOperations) if (!existingUids.has(uid(repairedTokens.get(operation.id), size))) {
    missing++;
    assert.equal(operation.id, "front", "only the actual missing process may be offered for issuance");
  }
}
assert.equal(missing, 6, "the missing payable No.1 must be offered once for each size");
const numbers = buildIssuedOperationNumbers(incidentOperations, issued, repairedTokens);
for (let sizeIndex = 0; sizeIndex < 6; sizeIndex++) {
  assert.equal(numbers.get(sizeIndex * 10 + 1), 5, "historical duplicate remains visible under its own number");
  assert.equal(numbers.get(sizeIndex * 10 + 2), 2);
  assert.equal(numbers.get(sizeIndex * 10 + 3), 3);
  assert.equal(numbers.get(sizeIndex * 10 + 4), 4, "same-name operations with different rates stay separate");
}
const newLabel = { ...issued[0], id: 100, label_uid: uid(repairedTokens.get("front"), "XL-50"), operation_name: "Chontak qoyish", rate_per_piece: 200 };
assert.deepEqual(buildOperationLabelTokens(incidentOperations, [...issued, newLabel]), repairedTokens, "new issuance and refresh stay idempotent");
assert.equal(buildIssuedOperationNumbers(incidentOperations, [...issued, newLabel]).get(100), 1);
const child = { ...issued[1], id: 101, label_uid: "OERP-SPLIT-EXAMPLE", split_from_label_id: issued[1].id, operation_name: "Corrected operation", payload: null };
assert.equal(buildIssuedOperationNumbers(incidentOperations, [...issued, child]).get(101), 2, "split children retain their parent's process number");
assert.equal(JSON.stringify(issued), before, "reconciliation must not mutate stored label identities, rates, or payloads");
console.log("Missing No.1, historical duplicates, same-name rates, six sizes, and split identity regressions passed.");

const rateEditedHistorical = issued.map((label, index) => index === 0 ? { ...label, payload: null, rate_per_piece: 75 } : label);
assert.deepEqual(buildOperationLabelTokens(incidentOperations, rateEditedHistorical), repairedTokens, "a rate-edited historical shared-code label must not hide No.1");
assert.equal(correctedOperationIdentityNeedsReview(incidentOperations, rateEditedHistorical), false, "unchanged operation names still identify rate corrections");
const renamedCurrent = issued.map((label, index) => index === 1 ? { ...label, payload: null, operation_name: "Explicitly corrected name" } : label);
assert.equal(correctedOperationIdentityNeedsReview(incidentOperations, renamedCurrent), true, "irretrievable renamed identity must require review, not issue a duplicate");
const rateEditedCurrent = issued.map((label, index) => index === 1 ? { ...label, payload: null, rate_per_piece: 75 } : label);
assert.equal(buildOperationLabelTokens(incidentOperations, rateEditedCurrent).get("planka"), originalTokens.get("planka"), "current process rate corrections preserve UID ownership");
const onlyHistoricalPlanka = issued.filter((label, index) => index % 4 === 0);
const insertedFirst = buildOperationLabelTokens(incidentOperations.slice(0, 2), onlyHistoricalPlanka);
assert.notEqual(insertedFirst.get("front"), "SEW-NEW");
assert.equal(insertedFirst.get("planka"), "SEW-NEW", "inserting a new first operation must retain the sole existing label of the old process");
assert.equal(buildIssuedOperationNumbers(incidentOperations.slice(0, 2), onlyHistoricalPlanka).get(1), 2);

const correctedEtak = issued.map((label, index) => index === 2 ? { ...label, payload: null, rate_per_piece: 250 } : label);
assert.deepEqual(buildOperationLabelTokens(incidentOperations, correctedEtak), repairedTokens, "editing a rate on same-name operations must retain their distinct existing tokens");
assert.equal(buildIssuedOperationNumbers(incidentOperations, correctedEtak).get(3), 3, "a corrected rate cannot move a label to another same-name operation number");
