import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/work-orders/[id]/sewing/page.tsx", "utf8");

const requiredPageContracts = [
  't("field.inputQty")',
  't("field.output")',
  't("field.failed")',
  "input_qty: numberOrZero(f.input_qty)",
  "rework_qty: 0",
  "rejected_qty: 0",
];

for (const contract of requiredPageContracts) {
  if (!page.includes(contract)) {
    throw new Error(`Missing pre-partial-size sewing contract: ${contract}`);
  }
}

for (const removedContract of [
  "/sewing-size-progress",
  "size_quantities",
  't("sewing.partialBySize")',
  't("sewing.recordNow")',
  't("field.rework")',
  't("field.rejected")',
  "f.rework_qty",
  "f.rejected_qty",
]) {
  if (page.includes(removedContract)) {
    throw new Error(`Unexpected Sewing control or partial-size contract: ${removedContract}`);
  }
}

console.log("Pre-partial-size Sewing UI contract passed.");
