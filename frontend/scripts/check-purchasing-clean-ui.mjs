import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import ts from "typescript";

const root = process.cwd();
const page = fs.readFileSync(path.join(root, "src/app/(app)/purchasing/page.tsx"), "utf8");
const dict = fs.readFileSync(path.join(root, "src/lib/i18n/dict.ts"), "utf8");

const requiredPageTokens = [
  "const [showRequestForm, setShowRequestForm] = useState(false)",
  "canRequest && !showRequestForm",
  "canRequest && showRequestForm",
  "grid grid-cols-1 gap-4 md:grid-cols-2",
  "filter((row) => row.id !== request.id)",
];
for (const token of requiredPageTokens) {
  if (!page.includes(token)) throw new Error(`Purchasing clean UI contract is missing: ${token}`);
}

// Check the existing business subset, rather than one spelling of its source.
const enumSource = ts.createSourceFile("purchaseRequestStatus.ts", fs.readFileSync(
  path.join(root, "src/lib/purchaseRequestStatus.ts"), "utf8"), ts.ScriptTarget.Latest, true);
const definition = enumSource.statements.find((node) => ts.isEnumDeclaration(node)
  && node.name.text === "PurchaseRequestStatus");
assert.ok(definition, "Canonical purchase request enum is missing");
const values = new Map(definition.members.map((member) => {
  assert.ok(member.initializer && ts.isStringLiteral(member.initializer));
  return [member.name.getText(enumSource), member.initializer.text];
}));
assert.deepEqual([...values.values()], ["draft", "pending_approval", "approved", "rejected", "converted"]);

function checkActiveStatuses(source) {
  const tree = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let initializer;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === "ACTIVE_REQUEST_STATUSES") {
      initializer = node.initializer;
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  assert.ok(initializer && ts.isNewExpression(initializer)
    && initializer.expression.getText(tree) === "Set", "Purchase request active subset must be explicit");
  const entries = initializer.arguments?.[0];
  assert.ok(entries && ts.isArrayLiteralExpression(entries));
  const actual = entries.elements.map((entry) => {
    assert.ok(ts.isPropertyAccessExpression(entry)
      && entry.expression.getText(tree) === "PurchaseRequestStatus", "Active statuses must use the canonical enum");
    assert.ok(values.has(entry.name.text), "Unknown purchase request enum member");
    return values.get(entry.name.text);
  });
  assert.deepEqual(actual, ["draft", "pending_approval", "approved"], "Purchase request active subset changed");
}
checkActiveStatuses(page);
const challenged = page.replace("PurchaseRequestStatus.APPROVED", "PurchaseRequestStatus.REJECTED");
assert.notEqual(challenged, page, "Active-subset challenge did not alter its input");
assert.throws(() => checkActiveStatuses(challenged), /Purchase request active subset changed/);

for (const removedToken of ["ShortageRow", "purchasing-shortages:", "page.purchasing.shortagesTitle", "createRequestFromSalesOrder"]) {
  if (page.includes(removedToken)) throw new Error(`Removed purchasing UI is still present: ${removedToken}`);
}

for (const label of ["New request", "Новая заявка", "Namuna yaratish"]) {
  if (!dict.includes(label)) throw new Error(`Missing purchasing action translation: ${label}`);
}

console.log("Purchasing clean UI contract OK");
