import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync("src/app/(app)/profile/page.tsx", "utf8");
const ast = ts.createSourceFile("profile.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const emailInputs = [];
function visit(node) {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === "input") {
    const attrs = node.attributes.properties;
    if (attrs.some((attr) => attr.name?.getText(ast) === "type" && attr.initializer?.getText(ast) === '"email"')) {
      emailInputs.push(attrs.map((attr) => attr.name?.getText(ast)));
    }
  }
  ts.forEachChild(node, visit);
}
visit(ast);
assert.equal(emailInputs.length, 1, "Profile has one email input");
assert.ok(emailInputs[0].includes("readOnly"), "Profile email input must be read-only");
assert.ok(!emailInputs[0].includes("onChange"), "Profile email input must not edit local state");
console.log("Profile email is read-only");
