import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const source = fs.readFileSync("src/lib/modelPaidOperations.ts", "utf8");
const javascript = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } }).outputText;
const { VALID_SECTIONS, normalizePaidOperation, serializePaidOperations, samePaidProcess } = await import(`data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`);
assert.equal(VALID_SECTIONS.length, 13);
for (const section of VALID_SECTIONS) {
  const operation = normalizePaidOperation({ id: `test-${section}`, section, name: "Test", code: "T", rate: "120" });
  assert.equal(serializePaidOperations([operation])[0].section, section);
}
const old = normalizePaidOperation({ id: "old", name: "Kontrol", section: "sewing", sourceStage: "Контроль", rate: "55" });
assert.equal(old.section, "control");
assert.equal(old.sourceStage, "Контроль");
assert.equal(serializePaidOperations([old])[0].rate, "55");
assert.ok(samePaidProcess(old, { name: "  KONTROL ", section: "control" }));
const edited = normalizePaidOperation({ ...old, section: "sewing", sourceStage: "sewing" });
assert.equal(edited.section, "sewing", "an intentional section change must survive reload");
assert.equal(normalizePaidOperation({ section: "sewing", sourceStage: "Tikuv" }).section, "tikuv");
console.log("All 13 paid sections, legacy metadata, deliberate edits and deduplication checks passed.");
