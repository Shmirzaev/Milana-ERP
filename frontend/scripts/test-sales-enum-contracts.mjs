import assert from "node:assert/strict";
import { test } from "node:test";
import ts from "typescript";
import { assertSalesEnumContract, readSalesSources } from "./check-sales-enum-contracts.mjs";

const source = readSalesSources();
test("actual Sales consumers preserve their typed vocabularies and behavior", () => assertSalesEnumContract(source));

// Locate the actual declaration rather than assuming its formatting or fields.
// Reject ambiguous/unsupported structures: a mutation must target real source.
function listRowDeclaration(contracts) {
  const tree = ts.createSourceFile("salesOrderContracts.ts", contracts, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  assert.equal(tree.parseDiagnostics.length, 0, "Sales contracts must parse without diagnostics");
  const aliases = tree.statements.filter((node) => ts.isTypeAliasDeclaration(node) && node.name.text === "SalesOrderListRow");
  assert.equal(aliases.length, 1, "Expected exactly one SalesOrderListRow declaration");
  const node = aliases[0];
  assert.ok(node.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword), "SalesOrderListRow must be exported");
  assert.ok(ts.isIntersectionTypeNode(node.type), "Expected a summary/list-shape intersection");
  assert.equal(node.type.types.length, 2, "Expected exactly two intersection members");
  const summaries = node.type.types.filter((item) => ts.isTypeReferenceNode(item) && ts.isIdentifier(item.typeName) && item.typeName.text === "SalesOrderSummary" && !item.typeArguments);
  const shapes = node.type.types.filter(ts.isTypeLiteralNode);
  assert.equal(summaries.length, 1, "Expected exactly one unparameterized SalesOrderSummary");
  assert.equal(shapes.length, 1, "Expected exactly one list-only type literal");
  const shape = shapes[0];
  const names = shape.members.map((member) => {
    assert.ok(ts.isPropertySignature(member) && member.name, "Unsupported list property");
    const name = member.name;
    if (ts.isIdentifier(name) || ts.isStringLiteral(name)) return name.text;
    if (ts.isComputedPropertyName(name) && ts.isStringLiteral(name.expression)) return name.expression.text;
    assert.fail("Unsupported computed list property");
  });
  assert.equal(new Set(names).size, names.length, "Ambiguous duplicate list property");
  assert.ok(!names.includes("status") && !names.includes("order_type"), "Existing shadow fields invalidate the challenge");
  const totals = shape.members.filter((_, index) => names[index] === "total_quantity");
  assert.equal(totals.length, 1, "Expected one total_quantity property");
  const total = totals[0];
  assert.ok(!total.questionToken && total.type?.kind === ts.SyntaxKind.NumberKeyword, "Expected required numeric total_quantity");
  return { tree, node, shape, total, literal: shape.getText(tree) };
}

function mutateListRow(contracts, fault) {
  const { tree, node, shape, total, literal } = listRowDeclaration(contracts);
  const original = node.type.getText(tree);
  let changed;
  if (fault === "reverse") changed = `${literal} & SalesOrderSummary`;
  else if (fault === "no_summary") changed = literal;
  else if (fault === "any_intersection") changed = `${original} & any`;
  else if (fault === "total_string") {
    const start = total.type.getStart(tree) - shape.getStart(tree);
    const end = total.type.end - shape.getStart(tree);
    changed = `SalesOrderSummary & ${literal.slice(0, start)}string${literal.slice(end)}`;
  } else {
    const fields = {
      status_string: "status: string;", status_quoted_any: '"status": any;',
      status_computed_any: '["status"]: any;', order_type_any: "order_type: any;",
      order_type_quoted_any: '"order_type": any;',
    };
    assert.ok(Object.hasOwn(fields, fault), "Unknown list-row mutation");
    assert.ok(literal.endsWith("}"), "Expected closing list-shape brace");
    changed = `SalesOrderSummary & ${literal.slice(0, -1)} ${fields[fault]} }`;
  }
  const mutated = contracts.slice(0, node.type.getStart(tree)) + changed + contracts.slice(node.type.end);
  assert.notEqual(mutated, contracts, "List-row challenge must alter actual source");
  return mutated;
}

for (const newline of ["\n", "\r\n"]) {
  test(`equivalent list intersection order preserves canonical types (${JSON.stringify(newline)})`, () => {
    const contracts = source.contracts.replace(/\r\n/g, "\n").replace(/\n/g, newline);
    assertSalesEnumContract({ ...source, contracts: mutateListRow(contracts, "reverse") });
  });
}
const faults = [
  ["enums", 'DRAFT = "draft"', 'DRAFT = "draft_bad"'],
  ["enums", 'FROM_STOCK = "from_stock"', 'FROM_STOCK = "first_grade"'],
  ["enums", '  SalesOrderType.BRANDED_STOCK_SALE,\n];', '  SalesOrderType.BRANDED_STOCK_SALE, SalesOrderType.BRANDED_STOCK,\n];'],
  ["contracts", 'status: SalesOrderStatus;', 'status: string;'],
  ["contracts", 'order_type: SalesOrderType;', 'order_type: any;'],
  ["list", 'type SO = SalesOrderListRow;', 'type SO = SalesOrderSummary;'],
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
  for (const fault of ["no_summary", "any_intersection", "status_string", "status_quoted_any", "status_computed_any", "order_type_any", "order_type_quoted_any", "total_string"]) test(`detect list-row ${fault} (${JSON.stringify(newline)})`, () => {
    const contracts = source.contracts.replace(/\r\n/g, "\n").replace(/\n/g, newline);
    const mutated = mutateListRow(contracts, fault);
    assert.throws(() => assertSalesEnumContract({ ...source, contracts: mutated }));
  });
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
