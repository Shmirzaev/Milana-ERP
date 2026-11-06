import assert from "node:assert/strict";
import { test } from "node:test";
import { assertInvoiceStatusContract, readInvoiceContractSources } from "./check-invoice-status-parity.mjs";

const sources = readInvoiceContractSources();

function withOrderStatus(type, prefix = "") {
  const statusField = /(type CustomerOrder = \{[\s\S]*?\bstatus:)\s*[^;]+;/;
  assert.match(sources.customerPage, statusField, "The challenge must locate CustomerOrder.status.");
  const customerPage = sources.customerPage.replace(
    statusField,
    `$1 ${type};`,
  );
  return { ...sources, customerPage: prefix + customerPage };
}

test("the current real source satisfies the invoice contract", () => {
  assertInvoiceStatusContract(sources);
});

test("a separate Sales-owned enum is allowed by the Finance guard", () => {
  assertInvoiceStatusContract(withOrderStatus("SalesOrderStatus", 'import type { SalesOrderStatus } from "@/lib/salesOrderStatus";\n'));
});

for (const type of ["InvoiceStatus", "InvoiceStatus | string", "Readonly<InvoiceStatus>"]) {
  test(`Sales status cannot borrow ${type}`, () => {
    assert.throws(() => assertInvoiceStatusContract(withOrderStatus(type)), /CustomerOrder.status must not borrow/);
  });
}

test("a local alias cannot disguise the invoice vocabulary as Sales status", () => {
  assert.throws(() => assertInvoiceStatusContract(withOrderStatus("SalesOrderStatus", "type SalesOrderStatus = InvoiceStatus;\n")),
    /CustomerOrder.status must not borrow/);
});

test("an import alias cannot disguise the invoice vocabulary as Sales status", () => {
  assert.throws(() => assertInvoiceStatusContract(withOrderStatus("WrongSalesStatus", 'import type { InvoiceStatus as WrongSalesStatus } from "@/lib/invoiceStatus";\n')),
    /CustomerOrder.status must not borrow/);
});

for (const key of ["financePage", "customerPage", "orderHistoryPage"]) {
  test(`${key} cannot substitute another module's InvoiceStatus`, () => {
    assert.throws(() => assertInvoiceStatusContract({ ...sources, [key]: sources[key].replace('"@/lib/invoiceStatus"', '"@/lib/wrongStatus"') }),
      /must import InvoiceStatus from the canonical module/);
  });
  for (const type of ["string", "any", "InvoiceStatus | string"]) {
    test(`${key} rejects an InvoiceRow.status escape to ${type}`, () => {
      const source = sources[key].replace(/(type InvoiceRow = \{[\s\S]*?\bstatus:) InvoiceStatus;/, `$1 ${type};`);
      assert.notEqual(source, sources[key]);
      // A decoy elsewhere must not satisfy the actual row's contract.
      assert.throws(() => assertInvoiceStatusContract({ ...sources, [key]: source + "\ntype Decoy = { status: InvoiceStatus };\n" }),
        /InvoiceRow.status must use exactly InvoiceStatus/);
    });
  }
}

test("a persisted vocabulary mismatch is rejected", () => {
  assert.throws(() => assertInvoiceStatusContract({ ...sources, invoiceStatusModule: sources.invoiceStatusModule.replace('PARTIALLY_PAID: "partially_paid"', 'PARTIALLY_PAID: "partial"') }),
    /frontend invoice status members must equal/);
});

test("payment methods remain free-form", () => {
  assert.throws(() => assertInvoiceStatusContract({ ...sources, financePage: sources.financePage.replace("payment_method: string", 'payment_method: "cash" | "bank_transfer"') }),
    /payment_method must stay free-form/);
});

test("the aggregate payment projection must not use persisted invoice states", () => {
  assert.throws(() => assertInvoiceStatusContract({ ...sources, customerPage: sources.customerPage.replace("payment_status: PaymentStatus", "payment_status: InvoiceStatus") }),
    /payment summary must not adopt/);
});
