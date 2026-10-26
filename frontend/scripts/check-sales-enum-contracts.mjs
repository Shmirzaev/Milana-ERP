import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import ts from "typescript";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const expectedStatus = ["draft", "pending_sales_approval", "confirmed", "planning", "planning_approved", "in_production", "production", "cutting", "printing", "sewing", "packaging", "storage", "ready_to_ship", "ready", "reserved", "shipped", "delivered", "closed", "cancelled"];
const expectedType = ["client_order", "branded_stock_sale", "branded_stock"];
const expectedSource = ["produce_new", "from_stock", "first_grade"];
export const sourcePaths = {
  enums: "src/lib/salesOrderEnums.ts", contracts: "src/lib/salesOrderContracts.ts",
  list: "src/app/(app)/sales-orders/page.tsx", create: "src/app/(app)/sales-orders/new/page.tsx",
  grade: "src/app/(app)/sales-orders/first-grade/page.tsx", detail: "src/app/(app)/sales-orders/[id]/page.tsx",
  history: "src/app/(app)/order-history/page.tsx", customer: "src/app/(app)/customers/[id]/page.tsx",
};
export function readSalesSources() {
  return Object.fromEntries(Object.entries(sourcePaths).map(([key, file]) => [key, readFileSync(path.join(root, file), "utf8")]));
}
export function transpile(source) {
  return ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
}
export function enumExports(source) {
  const exports = {};
  new Function("exports", transpile(source))(exports);
  return exports;
}
function file(source) { return ts.createSourceFile("source.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX); }
function declaration(source, name) {
  const tree = file(source);
  let found;
  function visit(node) {
    if ((ts.isVariableDeclaration(node) || ts.isFunctionDeclaration(node) || ts.isTypeAliasDeclaration(node)) && node.name?.getText(tree) === name) found = node;
    ts.forEachChild(node, visit);
  }
  visit(tree);
  assert.ok(found, `Missing actual declaration ${name}`);
  return { node: found, tree };
}
function property(source, type, name) {
  const { node, tree } = declaration(source, type);
  assert.ok(ts.isTypeLiteralNode(node.type), `${type} must expose its fields`);
  const member = node.type.members.find((member) => member.name?.getText(tree) === name);
  assert.ok(member?.type, `Missing ${type}.${name}`);
  return member.type.getText(tree);
}
export function listFunctions(sources) {
  const names = ["PRODUCTION_TAB_STATUSES", "INACTIVE_SALES_STATUSES", "matchesTab", "statusClass"];
  const body = names.map((name) => {
    const { node, tree } = declaration(sources.list, name);
    return ts.isFunctionDeclaration(node) ? node.getText(tree) : `const ${node.getText(tree)};`;
  }).join("\n");
  return new Function("enums", `const {SalesOrderStatus, SalesOrderType} = enums; ${transpile(body)}; return {${names.join(",")}};`)(enumExports(sources.enums));
}
export function creationPayload(source, scope) {
  const { node, tree } = declaration(source, "payload");
  const exports = {};
  new Function("exports", ...Object.keys(scope), transpile(`export const result = (${node.initializer.getText(tree)});`))(exports, ...Object.values(scope));
  return exports.result;
}
export function assertSalesEnumContract(sources) {
  const enums = enumExports(sources.enums);
  assert.deepEqual(Object.values(enums.SalesOrderStatus), expectedStatus, "Sales status vocabulary drift");
  assert.deepEqual(Object.values(enums.SalesOrderType), expectedType, "Sales type vocabulary drift");
  assert.deepEqual(Object.values(enums.SalesOrderItemSourceType), expectedSource, "Sales line source vocabulary drift");
  assert.deepEqual(enums.SALES_ORDER_CREATE_TYPES, expectedType.slice(0, 2), "Create must not offer shipment-only branded_stock");
  assert.equal(declaration(sources.enums, "SALES_ORDER_CREATE_TYPES").node.type.getText(), "readonly SalesOrderCreateType[]");
  for (const raw of ["client_order", "branded_stock_sale"]) assert.equal(enums.salesOrderCreateType(raw), raw);
  for (const raw of ["branded_stock", "", " CLIENT_ORDER ", "unknown"]) assert.equal(enums.salesOrderCreateType(raw), null);
  for (const [type, field, wanted] of [
    ["SalesOrderSummary", "status", "SalesOrderStatus"], ["SalesOrderSummary", "order_type", "SalesOrderType"],
    ["SalesOrderItem", "source_type", "SalesOrderItemSourceType"], ["SalesOrderItemInput", "source_type", "SalesOrderItemSourceType"],
    ["SalesOrderCreateInput", "order_type", "SalesOrderCreateType"],
  ]) assert.equal(property(sources.contracts, type, field), wanted, `${type}.${field} must use its canonical type`);
  assert.match(sources.list, /useLoadMore<\{ rows: SO\[\]; total: number \}>/);
  assert.match(sources.list, /type SO = SalesOrderSummary;/);
  assert.match(sources.detail, /useSWR<SalesOrderDetailContract>/);
  assert.match(sources.create, /useState<SalesOrderCreateType>\(SalesOrderType.CLIENT_ORDER\)/);
  for (const key of ["create", "grade"]) assert.equal(declaration(sources[key], "payload").node.type.getText(), "SalesOrderCreateInput");
  for (const key of ["list", "create", "grade", "detail", "history", "customer"]) assert.match(sources[key], /from "@\/lib\/salesOrderEnums";/, `${key} must import its canonical Sales vocabulary`);
  for (const name of ["PRODUCTION_TAB_STATUSES", "INACTIVE_SALES_STATUSES"]) assert.equal(declaration(sources.list, name).node.type.getText(), "readonly SalesOrderStatus[]");
  for (const name of ["INVOICE_ACTION_STATUSES", "RESERVED_SALES_STATUSES"]) assert.equal(declaration(sources.detail, name).node.type.getText(), "readonly SalesOrderStatus[]");
  assert.equal(property(sources.customer, "CustomerOrder", "status"), "SalesOrderStatus");
  assert.match(sources.history, /record_type: "sales_order"; order_type: SalesOrderType; status: SalesOrderStatus/);
  assert.match(sources.history, /record_type: "production_order"; order_type: string; status: string/);
  for (const key of ["history", "customer"]) assert.equal(property(sources[key], "InvoiceRow", "status"), "InvoiceStatus", "Invoice remains Finance-owned");
  const funcs = listFunctions(sources);
  assert.deepEqual(funcs.PRODUCTION_TAB_STATUSES, ["production", "planning", "confirmed"]);
  assert.deepEqual(funcs.INACTIVE_SALES_STATUSES, ["closed", "cancelled", "delivered"]);
  for (const status of [...expectedStatus, "late", "legacy_unknown"]) {
    const expected = { all: true, production: ["production", "planning", "confirmed"].includes(status), late: status === "late", shipping: status === "ready", draft: status === "draft" };
    for (const [tab, match] of Object.entries(expected)) assert.equal(funcs.matchesTab({status}, tab), match, `${status}/${tab}`);
  }
  for (const orderType of ["client_order", "branded_stock_sale"]) {
    const scope = { ...enums, customerId: "", orderType, deadline: "", hasPrintingSelected: false, printingInstructions: "untouched", printingAttachments: [], notes: "n", isBrandedOrder: orderType === "branded_stock_sale", BRANDED_PACK_COLOR: "mixed", brandedPackSize: "any", brandId: "", linePacks: row => row.pack_count, linePieces: row => row.quantity, numberOrZero: Number,
      lines: [{model_id: 2, color: "blue", size: "46", quantity: 3, pack_count: 2, unit_price: "", printing_required: true}] };
    const payload = creationPayload(sources.create, scope);
    const pack = orderType === "branded_stock_sale";
    assert.deepEqual(payload, { customer_id: null, order_type: orderType, deadline: null, printing_instructions: null, printing_attachments: [], notes: "n", items: [{ model_id: 2, color: pack ? "mixed" : "blue", size: pack ? "any" : "46", ...(pack ? {requested_pack_count: 2} : {quantity: 3}), unit_price: null, printing_required: !pack, brand_id: null }] }, "Create payload changed defaults, count policy or omitted source type");
  }
  assert.deepEqual(creationPayload(sources.grade, {...enums, customer: "4", selected: [{model_id: 2, color: "blue", size: "46", quantity: "3", price: "0"}]}), {order_type: "branded_stock_sale", customer_id: 4, items: [{model_id: 2, color: "blue", size: "46", quantity: 3, unit_price: 0, source_type: "first_grade"}]});
  return {status_values: 19, order_types: 3, item_sources: 3, list_policy_cases: 105, creation_payload_cases: 3};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(JSON.stringify({result: "PASS", ...assertSalesEnumContract(readSalesSources())}));
}
