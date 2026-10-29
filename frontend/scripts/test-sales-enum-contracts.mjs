import assert from "node:assert/strict";
import { test } from "node:test";
import { assertSalesEnumContract, readSalesSources } from "./check-sales-enum-contracts.mjs";

const source = readSalesSources();
test("actual Sales consumers preserve their typed vocabularies and behavior", () => assertSalesEnumContract(source));
test("equivalent list intersection order preserves canonical types", () => {
  const contracts = source.contracts.replace(
    'SalesOrderSummary & { total_quantity: number }',
    '{ total_quantity: number } & SalesOrderSummary',
  );
  assert.notEqual(contracts, source.contracts);
  assertSalesEnumContract({ ...source, contracts });
});
const faults = [
  ["enums", 'DRAFT = "draft"', 'DRAFT = "draft_bad"'],
  ["enums", 'FROM_STOCK = "from_stock"', 'FROM_STOCK = "first_grade"'],
  ["enums", '  SalesOrderType.BRANDED_STOCK_SALE,\n];', '  SalesOrderType.BRANDED_STOCK_SALE, SalesOrderType.BRANDED_STOCK,\n];'],
  ["contracts", 'status: SalesOrderStatus;', 'status: string;'],
  ["contracts", 'order_type: SalesOrderType;', 'order_type: any;'],
  ["list", 'type SO = SalesOrderListRow;', 'type SO = SalesOrderSummary;'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = { total_quantity: number };'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number } & any;'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = SalesOrderSummary & { status: string; total_quantity: number };'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = SalesOrderSummary & { "status": any; total_quantity: number };'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = SalesOrderSummary & { ["status"]: any; total_quantity: number };'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = SalesOrderSummary & { order_type: any; total_quantity: number };'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = SalesOrderSummary & { "order_type": any; total_quantity: number };'],
  ["contracts", 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: number };', 'export type SalesOrderListRow = SalesOrderSummary & { total_quantity: string };'],
  ["contracts", 'source_type?: SalesOrderItemSourceType;', 'source_type?: SalesOrderItemSourceType | string;'],
  ["list", 'SalesOrderStatus.CONFIRMED];', 'SalesOrderStatus.CONFIRMED, SalesOrderStatus.PRINTING];'],
  ["list", 'readonly SalesOrderStatus[]', 'readonly string[]'],
  ["detail", 'useSWR<SalesOrderDetailContract>', 'useSWR<any>'],
  ["create", 'useState<SalesOrderCreateType>(SalesOrderType.CLIENT_ORDER)', 'useState<SalesOrderCreateType>(SalesOrderType.BRANDED_STOCK_SALE)'],
  ["create", 'const payload: SalesOrderCreateInput', 'const payload: any'],
  ["create", 'unit_price: line.unit_price === "" ? null : numberOrZero(line.unit_price)', 'unit_price: line.unit_price === "" ? 0 : numberOrZero(line.unit_price)'],
  ["grade", 'source_type: SalesOrderItemSourceType.FIRST_GRADE', 'source_type: SalesOrderItemSourceType.FROM_STOCK'],
  ["customer", 'status: SalesOrderStatus;', 'status: InvoiceStatus;'],
  ["history", 'record_type: "production_order"; order_type: string; status: string', 'record_type: "production_order"; order_type: SalesOrderType; status: SalesOrderStatus'],
];
// Match the same fault against LF checkouts and CRLF archive blobs. Normalize
// only the test's mutation input; the unchanged-source test above uses raw bytes.
for (const newline of ["\n", "\r\n"]) {
  for (const [key, before, after] of faults) test(`detect ${key} (${JSON.stringify(newline)}): ${before}`, () => {
    const withLineEndings = source[key].replace(/\r\n/g, "\n").replace(/\n/g, newline);
    const mutationSource = withLineEndings.replace(/\r\n/g, "\n");
    assert.ok(mutationSource.includes(before), "Fault challenge must modify actual source");
    const mutated = mutationSource.replace(before, after);
    assert.notEqual(mutated, mutationSource, "Fault challenge must change the matched source");
    assert.throws(() => assertSalesEnumContract({...source, [key]: mutated}));
  });
}

function withProductionTypes(orderType, status, prefix = "") {
  const branch = 'record_type: "production_order"; order_type: string; status: string';
  assert.ok(source.history.includes(branch), "Challenge must replace the actual Production branch");
  return { ...source, history: prefix + source.history.replace(branch,
    `record_type: "production_order"; order_type: ${orderType}; status: ${status}`) };
}

test("future distinct Production enums are allowed", () => {
  assertSalesEnumContract(withProductionTypes("ProductionOrderType", "ProductionOrderStatus",
    'enum ProductionOrderType { STOCK = "stock" }\nenum ProductionOrderStatus { IN_PROGRESS = "in_progress" }\n'));
});

test("future imported Production enums and owner aliases are allowed", () => {
  assertSalesEnumContract(withProductionTypes("ProductionOrderType", "ProductionStatus",
    'import type { ProductionOrderType, ProductionOrderStatus } from "@/lib/productionOrderEnums";\ntype ProductionStatus = ProductionOrderStatus;\n'));
});

for (const [orderType, status] of [
  ["SalesOrderType", "string"], ["string", "SalesOrderStatus"],
  ["SalesOrderCreateType", "string"],
  ["string", "SalesOrderStatus | string"], ["Readonly<SalesOrderType>", "string"],
]) test(`Production cannot borrow ${orderType}/${status}`, () => {
  assert.throws(() => assertSalesEnumContract(withProductionTypes(orderType, status)), /must not borrow Sales enum types/);
});

test("a local alias cannot disguise Sales status as Production", () => {
  assert.throws(() => assertSalesEnumContract(withProductionTypes("string", "ProductionStatus",
    'type IntermediateStatus = SalesOrderStatus;\ntype ProductionStatus = IntermediateStatus;\n')), /must not borrow Sales enum types/);
});

test("an import alias cannot disguise a Sales order type as Production", () => {
  assert.throws(() => assertSalesEnumContract(withProductionTypes("ProductionType", "string",
    'import type { SalesOrderType as ProductionType } from "@/lib/salesOrderEnums";\n')), /must not borrow Sales enum types/);
});

test("namespace-qualified Sales types cannot bypass the Production boundary", () => {
  assert.throws(() => assertSalesEnumContract(withProductionTypes("string", "Sales.SalesOrderStatus",
    'import type * as Sales from "@/lib/salesOrderEnums";\n')), /must not borrow Sales enum types/);
});

test("an import alias and local alias cannot disguise the Sales create subset", () => {
  assert.throws(() => assertSalesEnumContract(withProductionTypes("ProductionType", "string",
    'import type { SalesOrderCreateType as ImportedType } from "@/lib/salesOrderEnums";\ntype ProductionType = ImportedType;\n')), /must not borrow Sales enum types/);
});

for (const name of ["SalesOrderStatus", "SalesOrderType", "SalesOrderItemSourceType", "SalesOrderCreateType"]) {
  test(`inline import cannot disguise ${name} as Production`, () => {
    assert.throws(() => assertSalesEnumContract(withProductionTypes("string", `import("@/lib/salesOrderEnums").${name}`)), /must not borrow Sales enum types/);
  });
}

test("local aliases cannot disguise inline Sales imports", () => {
  assert.throws(() => assertSalesEnumContract(withProductionTypes("ProductionType", "string",
    'type ImportedType = import("@/lib/salesOrderEnums").SalesOrderCreateType;\ntype ProductionType = ImportedType;\n')), /must not borrow Sales enum types/);
});

test("inline imports of distinct Production owner types remain allowed", () => {
  assertSalesEnumContract(withProductionTypes('import("@/lib/productionOrderEnums").ProductionOrderType', "ProductionStatus",
    'type ProductionStatus = import("@/lib/productionOrderEnums").ProductionOrderStatus;\n'));
});

test("the production_order discriminator must remain present", () => {
  const history = source.history.replace('record_type: "production_order";', 'record_type: "other";');
  assert.notEqual(history, source.history);
  assert.throws(() => assertSalesEnumContract({ ...source, history }), /production_order discriminator/);
});
