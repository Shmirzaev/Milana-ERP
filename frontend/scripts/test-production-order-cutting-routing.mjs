import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const parts = [];
function visit(node) {
  if (ts.isVariableDeclaration(node) && ["allProdOrders", "prodOrdersArr"].includes(node.name.getText(ast))) parts.push(`const ${node.getText(ast)};`);
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(parts.length, 2);
const code = ts.transpileModule(parts.join("\n"), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText;
const select = new Function("prodOrders", "cuttingDepartment", `${code};return prodOrdersArr;`);
const rows = [{ id: 1, cutting_department_code: "CUT" }, { id: 2, cutting_department_code: "ECT" },
  { id: 3, cutting_department_code: null }, { id: 4 }, { id: 5, cutting_department_code: "UNKNOWN" }];
for (const input of [rows, { rows }]) {
  assert.deepEqual(select(input, "ECT").map(row => row.id), [2]);
  assert.deepEqual(select(input, "CUT").map(row => row.id), [1], "Unknown/ambiguous routing cannot be guessed into Milana");
}
console.log("Actual passport order selector uses exact Cutting routing for plain/paginated results and excludes ambiguous orders.");
