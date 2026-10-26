import assert from "node:assert/strict";
import { test } from "node:test";
import { assertSalesEnumContract, readSalesSources } from "./check-sales-enum-contracts.mjs";

const source = readSalesSources();
test("actual Sales consumers preserve their typed vocabularies and behavior", () => assertSalesEnumContract(source));
const faults = [
  ["enums", 'DRAFT = "draft"', 'DRAFT = "draft_bad"'],
  ["enums", 'FROM_STOCK = "from_stock"', 'FROM_STOCK = "first_grade"'],
  ["enums", '  SalesOrderType.BRANDED_STOCK_SALE,\n];', '  SalesOrderType.BRANDED_STOCK_SALE, SalesOrderType.BRANDED_STOCK,\n];'],
  ["contracts", 'status: SalesOrderStatus;', 'status: string;'],
  ["contracts", 'order_type: SalesOrderType;', 'order_type: any;'],
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
for (const [key, before, after] of faults) test(`detect ${key}: ${before}`, () => {
  assert.ok(source[key].includes(before), "Fault challenge must modify actual source");
  assert.throws(() => assertSalesEnumContract({...source, [key]: source[key].replace(before, after)}));
});
