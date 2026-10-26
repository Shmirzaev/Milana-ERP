import assert from "node:assert/strict";
import fs from "node:fs";
import { runtimeMessages } from "./runtime-locales.mjs";

const page = fs.readFileSync("src/app/(app)/payroll/reports/sewing-production/page.tsx", "utf8");
const table = fs.readFileSync("src/components/payroll/SewingProductionReportTable.tsx", "utf8");
const translations = ["en", "ru", "uz"].map(runtimeMessages);
const printTable = table.slice(table.indexOf('className="sewing-report-print-table'));

assert.match(table, /sewing-report-print-table/, "The report needs a dedicated compact print table");
assert.match(printTable, /formatModelVariantCode\(row\.model_code\), row\.size/, "The compact report must retain the formatted variant and size context");
assert.doesNotMatch(
  printTable,
  /row\.sewing_line|row\.cutting_reference|row\.product_name|row\.operation_code &&/,
  "The compact print table must omit repeated production metadata and internal operation-code detail",
);
assert.match(page, /qrCount: printRows \? reportRows\.length/, "Printed QR total must count all fetched report rows");
assert.match(page, /sum \+ Number\(row\.quantity/, "Printed completed-work total must sum row quantities");
assert.match(page, /sum \+ Number\(row\.rate_per_piece/, "Printed average-rate total must sum every row rate");
assert.match(page, /sum \+ Number\(row\.total_amount/, "Printed payroll total must sum row amounts");
assert.match(page, /font-weight: 700 !important/, "Printed report text must use bold weight");
assert.match(page, /page-break-inside: avoid !important/, "The final totals block must stay together");

for (const key of [
  "page.sewingReport.printTotals",
  "page.sewingReport.scannedQrCount",
  "page.sewingReport.totalCompletedPieces",
  "page.sewingReport.totalRate",
]) {
  assert.ok(translations.every(messages => messages.has(key)), `${key} must exist in all runtime languages`);
}

console.log("Sewing production print contract passed.");
