import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";

const exports = {};
new Function("exports", ts.transpile(fs.readFileSync(new URL("../src/lib/employeeNumberPayload.ts", import.meta.url), "utf8"), {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
}))(exports);

test("unchanged legacy employee number is omitted from updates", () => {
  assert.deepEqual(exports.employeeNumberPayload("UX-ACTIVE-205", "UX-ACTIVE-205"), {});
  assert.deepEqual(exports.employeeNumberPayload("UX-ACTIVE-205", "537002"), { employee_no: "537002" });
  assert.deepEqual(exports.employeeNumberPayload(undefined, "537001"), { employee_no: "537001" });
  assert.deepEqual(exports.employeeNumberPayload(null, ""), {});
});
