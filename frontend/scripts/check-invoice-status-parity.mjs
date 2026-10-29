import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import ts from "typescript";

// The persisted invoice vocabulary is shared with the backend. Sources are
// resolved relative to this script, so it works from any working directory.
// It is a standalone script and is not part of the frontend build.
export function readInvoiceContractSources() {
  const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
  return {
    invoiceStatusModule: read("../src/lib/invoiceStatus.ts"),
    backendEnum: read("../../backend/app/libs/enums/finance.py"),
    financePage: read("../src/app/(app)/finance/page.tsx"),
    orderHistoryPage: read("../src/app/(app)/order-history/page.tsx"),
    customerPage: read("../src/app/(app)/customers/[id]/page.tsx"),
  };
}

// Inspect the named row, not an unrelated annotation or a commented example.
function rowProperty(source, rowName, propertyName) {
  const file = ts.createSourceFile("consumer.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const row = file.statements.find((node) => ts.isTypeAliasDeclaration(node) && node.name.text === rowName);
  assert.ok(row && ts.isTypeLiteralNode(row.type), `${rowName} must declare its row shape.`);
  const property = row.type.members.find((node) => ts.isPropertySignature(node) && node.name.getText(file) === propertyName);
  assert.ok(property?.type, `${rowName}.${propertyName} must declare a type.`);
  return { file, type: property.type };
}

export function assertInvoiceStatusContract({ invoiceStatusModule, backendEnum, financePage, orderHistoryPage, customerPage }) {

  // The backend members, read from the canonical enum class.
  const backendClass = backendEnum.match(/class InvoiceStatus\(str, Enum\):\r?\n([\s\S]*?)(?=\r?\n\S|$)/);
  assert.ok(backendClass, "The backend InvoiceStatus enum class must exist.");
  const backendMembers = [...backendClass[1].matchAll(/^[ \t]+[A-Z_]+[ \t]*=[ \t]*"([^"]+)"/gm)].map((match) => match[1]);

  // Read literal members without executing application source as JavaScript.
  const enumFile = ts.createSourceFile("invoiceStatus.ts", invoiceStatusModule, ts.ScriptTarget.Latest, true);
  const declaration = enumFile.statements.filter(ts.isVariableStatement)
    .flatMap((node) => [...node.declarationList.declarations])
    .find((node) => node.name.getText(enumFile) === "INVOICE_STATUS");
  const initializer = declaration?.initializer;
  assert.ok(initializer && ts.isAsExpression(initializer) && ts.isObjectLiteralExpression(initializer.expression),
    "The canonical frontend INVOICE_STATUS const object must exist.");
  const frontendMembers = initializer.expression.properties.map((member) => {
    assert.ok(ts.isPropertyAssignment(member) && ts.isStringLiteral(member.initializer),
      "Invoice status members must be literal strings.");
    return member.initializer.text;
  });

  assert.equal(backendMembers.length, 5, "The backend invoice status vocabulary must keep exactly five members.");
  assert.equal(frontendMembers.length, 5, "The frontend invoice status vocabulary must keep exactly five members.");
  assert.deepEqual(
    frontendMembers,
    backendMembers,
    "The frontend invoice status members must equal the backend InvoiceStatus members, in the same order.",
  );
  assert.match(
    invoiceStatusModule,
    /export type InvoiceStatus = \(typeof INVOICE_STATUS\)\[keyof typeof INVOICE_STATUS\];/,
    "The frontend must publish the canonical InvoiceStatus type.",
  );

  // The live consumers speak the canonical type and compare canonical members.
  for (const [name, source] of [
    ["finance page", financePage],
    ["order-history page", orderHistoryPage],
    ["customer detail page", customerPage],
  ]) {
    const { file, type } = rowProperty(source, "InvoiceRow", "status");
    assert.equal(type.getText(file), "InvoiceStatus", `${name} InvoiceRow.status must use exactly InvoiceStatus.`);
    const canonicalImport = file.statements.some((node) => {
      if (!ts.isImportDeclaration(node) || node.moduleSpecifier.text !== "@/lib/invoiceStatus") return false;
      const bindings = node.importClause?.namedBindings;
      return bindings && ts.isNamedImports(bindings) && bindings.elements.some((entry) =>
        entry.name.text === "InvoiceStatus" && (entry.propertyName ?? entry.name).text === "InvoiceStatus");
    });
    assert.ok(canonicalImport, `${name} must import InvoiceStatus from the canonical module.`);
  }

  assert.match(financePage, /inv\.status === INVOICE_STATUS\.PAID/, "The paid badge must compare the canonical member.");
  assert.match(financePage, /inv\.status !== INVOICE_STATUS\.PAID/, "The payment button must compare the canonical member.");
  assert.doesNotMatch(
    financePage,
    /String\(inv\.status\)\.toLowerCase\(\)/,
    "The invoice status must not be normalised through a raw string comparison.",
  );

  // The button policy is unchanged: only a paid invoice hides the payment
  // action, so a reversed invoice still offers it and the backend refuses the
  // payment with its 409 business response. Do not change that silently.
  assert.match(
    financePage,
    /\{inv\.status !== INVOICE_STATUS\.PAID \? \(/,
    "The payment action must stay hidden only for a paid invoice.",
  );

  // payment_method stays free-form text. The known dropdown options do not make
  // the stored or submitted payment method a closed enum.
  assert.match(financePage, /payment_method: string/, "payment_method must stay free-form text.");
  assert.match(financePage, /payment_method: payment\.payment_method,/, "The payment request must keep sending the chosen method unchanged.");

  // The customer order-level payment summary is a separate projection and keeps
  // its own vocabulary.
  assert.match(
    customerPage,
    /type PaymentStatus = "paid" \| "partial" \| "unpaid" \| "no_invoice" \| "void" \| "cancelled";/,
    "The customer order-level payment summary must keep its own projection vocabulary.",
  );
  assert.ok(
    !/payment_status: InvoiceStatus/.test(customerPage),
    "The customer order-level payment summary must not adopt the invoice vocabulary.",
  );
  // Sales may adopt its own canonical status type. This Finance guard forbids
  // borrowing InvoiceStatus; it does not require Sales to stay untyped forever.
  const { file: customerFile, type: orderStatus } = rowProperty(customerPage, "CustomerOrder", "status");
  const aliases = new Map(customerFile.statements.filter(ts.isTypeAliasDeclaration).map((node) => [node.name.text, node.type]));
  const invoiceNames = new Set(["InvoiceStatus"]);
  for (const node of customerFile.statements) {
    if (!ts.isImportDeclaration(node) || node.moduleSpecifier.text !== "@/lib/invoiceStatus") continue;
    const bindings = node.importClause?.namedBindings;
    if (bindings && ts.isNamedImports(bindings)) {
      for (const entry of bindings.elements) {
        if ((entry.propertyName ?? entry.name).text === "InvoiceStatus") invoiceNames.add(entry.name.text);
      }
    }
  }
  function borrowsInvoiceType(node, seen = new Set()) {
    if (ts.isTypeReferenceNode(node)) {
      const name = node.typeName.getText(customerFile);
      if (invoiceNames.has(name)) return true;
      if (aliases.has(name) && !seen.has(name)) {
        if (borrowsInvoiceType(aliases.get(name), new Set([...seen, name]))) return true;
      }
    }
    return Boolean(ts.forEachChild(node, (child) => borrowsInvoiceType(child, seen) || undefined));
  }
  assert.ok(!borrowsInvoiceType(orderStatus), "CustomerOrder.status must not borrow the InvoiceStatus vocabulary.");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  assertInvoiceStatusContract(readInvoiceContractSources());
  console.log("Invoice status contract passed: five-member backend/frontend parity and canonical usage.");
}
