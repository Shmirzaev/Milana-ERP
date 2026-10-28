import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/garmentSizes.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { GARMENT_SIZE_OPTIONS, garmentSizeRange, garmentSizeRangeEndOptions } = await import(
  `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`
);
const children = ["98", "104", "110", "116", "122", "128", "134", "140", "146", "152", "158", "164", "170", "176"];
assert.deepEqual(garmentSizeRange("98", "176"), children);
assert.deepEqual(garmentSizeRange("110", "134"), ["110", "116", "122", "128", "134"]);
assert.deepEqual(garmentSizeRange("176", "176"), ["176"]);
assert.deepEqual(garmentSizeRange("46", "56"), ["46", "48", "50", "52", "54", "56"]);
assert.deepEqual(garmentSizeRangeEndOptions("64"), ["64", "66", "68"]);
assert.deepEqual(garmentSizeRangeEndOptions("170"), ["170", "176"]);
for (const [from, to] of [["68", "98"], ["44", "176"], ["98", "68"], ["176", "98"], ["102", "110"], ["", ""]]) {
  assert.deepEqual(garmentSizeRange(from, to), [], `reject invalid or mixed family range ${from}â€“${to}`);
}
assert.equal(new Set(GARMENT_SIZE_OPTIONS).size, GARMENT_SIZE_OPTIONS.length);
assert.equal(GARMENT_SIZE_OPTIONS.length, 28);
for (const size of GARMENT_SIZE_OPTIONS) assert.deepEqual(garmentSizeRange(size, size), [size]);

// Both saving flows must use the same family-aware expansion and end choices.
for (const path of ["../src/components/ManualModelSizes.tsx", "../src/app/(app)/models/[id]/page.tsx"]) {
  const page = readFileSync(new URL(path, import.meta.url), "utf8");
  assert.match(page, /garmentSizeRange\(/);
  assert.match(page, /garmentSizeRangeEndOptions\(/);
  assert.match(page, /!garmentSizeRangeEndOptions\(next\)\.includes\(/);
}
console.log("Garment size ranges: all child sizes, adult compatibility, family boundaries and both saving flows passed.");
