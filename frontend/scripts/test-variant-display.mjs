import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

async function load(path) {
  const js = ts.transpileModule(fs.readFileSync(path, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
}
const { formatVariantNumber, formatModelVariantCode } = await load("src/lib/variantDisplay.ts");
const { splitModelCode, modelCodeParts, modelSearchIncludes } = await load("src/lib/modelCode.ts");
for (const [raw, expected] of [["3596", "V-3596"], ["V-5865", "V-5865"], [" v = 0052 ", "V-0052"], ["V-V=6135", "V-6135"], ["Ф-2095", "V-Ф-2095"], [null, ""], ["", ""], ["—", ""], ["-", ""], ["V-", ""]]) {
  assert.equal(formatVariantNumber(raw), expected);
  assert.equal(formatVariantNumber(expected), expected);
}
for (const [raw, expected] of [["PJ1095-3596", "PJ1095-V-3596"], ["PJ1095-V=3596", "PJ1095-V-3596"], ["PJ1095-V-3596", "PJ1095-V-3596"], ["PJ-1095", "PJ-1095"], ["PJ1095", "PJ1095"], [null, ""]]) {
  assert.equal(formatModelVariantCode(raw), expected);
  assert.equal(formatModelVariantCode(expected), expected);
}
assert.deepEqual(splitModelCode("PJ1095-V-5865"), { modelNo: "PJ1095", variantNo: "V-5865", code: "PJ1095-V-5865" });
const original = { code: "PJ1095-3596", details_json: { general: { model_no: "PJ1095", variant_no: "3596" } } };
assert.equal(formatVariantNumber(modelCodeParts(original).variantNo), "V-3596");
assert.equal(original.details_json.general.variant_no, "3596", "Display formatting preserves stored identity");
assert.equal(modelCodeParts({ code: "BASE-12", details_json: { general: { model_no: "BASE-12" } } }).variantNo, "", "Base models do not gain a variant");
assert.ok(modelSearchIncludes("PJ1095-3596", "V-3596"));
assert.ok(modelSearchIncludes("PJ1095-V-3596", "PJ1095-3596"));
console.log("Variant display regression checks passed");
