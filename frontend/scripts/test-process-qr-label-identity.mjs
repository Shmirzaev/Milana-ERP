import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const helperSource = fs.readFileSync("src/lib/processQrLabelIdentity.ts", "utf8");
const helperJavaScript = ts.transpileModule(helperSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const helperModuleUrl = `data:text/javascript;base64,${Buffer.from(helperJavaScript).toString("base64")}`;
const { buildOperationLabelTokens } = await import(helperModuleUrl);

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
