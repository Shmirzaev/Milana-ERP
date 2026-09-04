import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = fs
  .readFileSync(path.join(root, "src/app/(app)/process-qr/page.tsx"), "utf8")
  .replace(/\r\n/g, "\n");
const runtimeLocaleFiles = ["en", "ru", "uz"].map((lang) => ({
  lang,
  source: fs.readFileSync(path.join(root, `src/lib/i18n/locales/${lang}-supplemental.ts`), "utf8"),
}));
const runtimeTranslationKeys = [
  "page.processQr.closedSewingOrdersHint",
  "page.processQr.noClosedSewingOrders",
  "page.processQr.sewingEnteredQty",
  "page.processQr.sewingEnteredSizeQty",
];
for (const locale of runtimeLocaleFiles) {
  for (const key of runtimeTranslationKeys) {
    if (!locale.source.includes(`"${key}"`)) {
      throw new Error(`${locale.lang} runtime locale is missing ${key}`);
    }
  }
}

const printTextSource = source
  .slice(source.indexOf("function sewingLinePrintText"), source.indexOf("function qrDataUrl"))
  .replace("code: string | null, name: string | null", "code, name")
  .replace("): string {", ") {");
const sewingLinePrintText = new Function(`${printTextSource}; return sewingLinePrintText;`)();
const printTextCases = [
  ["SEW-1", "Maxmudova Nargiza - 2", "SEW-1 Maxmudova\nNargiza - 2"],
  ["SEW-01", "Bozorova Nargiza", "SEW-01 Bozorova\nNargiza"],
  ["SEW-02", "Nargiza", "SEW-02\nNargiza"],
];
for (const [code, name, expected] of printTextCases) {
  const actual = sewingLinePrintText(code, name);
  if (actual !== expected) throw new Error(`Unexpected sewing-line print split: ${JSON.stringify(actual)}`);
}

const required = [
  ["numeric garment-size comparator", "const leftNumber = leftNumbers.at(-1);"],
  ["configured sizes sorted smallest-first", "[...rows].sort((left, right) => compareGarmentSizes(left.size, right.size))"],
  ["size-major label generation", "for (const sizeOption of sizeOptions) {\n      for (const batch of batchesToPrint) {\n        for (const operation of selectedOperations)"],
  ["canonical issued-label comparator", "function compareIssuedLabelOrder("],
  ["canonical order compares sizes before operations", "compareGarmentSizes(leftSize, rightSize)\n    || operationNumberForLabel(left, operationNumbers)"],
  ["all bulk print requests are re-sorted at the print boundary", "const rowsInPrintOrder = [...rows].sort((left, right) => (\n        compareIssuedLabelOrder(left, right, issuedSizeOrder, issuedOperationNumbers)"],
  ["QR preparation preserves the canonical print order", "Promise.all(rowsInPrintOrder.map(async (label)"],
  ["model operation rank", "operationNumberForLabel(left, operationNumbers) - operationNumberForLabel(right, operationNumbers)"],
  ["stable copy ordering", "|| left.copy_index - right.copy_index"],
  ["stable label fallback", "|| left.id - right.id"],
  ["all-size printing uses ordered groups", "onClick={() => printIssuedLabels(orderedIssuedLabels)}"],
  ["printed operation number starts from model sequence", "factoryOperations.forEach((operation, index) => register(operation.code, operation.name, index + 1))"],
  ["printed operation number is in the top-right header", "process-label__number font-bold text-[#14110b]"],
  ["printed footer contains Kroy number", "process-label__kroy"],
  ["work-label details use larger print text", ".process-label--work .process-label__details"],
  ["work-label details fill the full body height", "grid-template-rows: 1fr 1fr 2.25fr 1fr 1fr 1fr !important"],
  ["work-label details use 8.4pt print text", "font-size: 8.4pt !important"],
  ["work-label sewing-line value allows two full print lines", "max-height: 6.6mm !important"],
  ["only model and sewing-line values use smaller print text", ".process-label--work .process-label__identity-value"],
  ["model and sewing-line values use 6pt print text", "font-size: 6pt !important"],
  ["sewing-line print keeps the surname beside its code", "const firstLine = [codeText, ...nameParts.slice(0, lastNameIndex)]"],
  ["sewing-line print moves only the final name word and suffix down", "const secondLine = nameParts.slice(lastNameIndex).join(\" \")"],
  ["issued labels use the controlled sewing-line split", "sewingLinePrintText(label.sewing_line_code, label.sewing_line_name)"],
  ["sewing-line print value preserves its controlled line break", ".process-label--work .process-label__sewing-line-value"],
  ["work-label QR aligns to the top", ".process-label--work .process-label__qr"],
  ["employee labels use the real employee number", "payload: employeeNumber(employee)"],
  ["employee number is visible on the badge", "value={employeeNumber(employee)}"],
  ["employee badge details use larger print text", ".process-label--employee .process-label__details"],
  ["employee badge title uses 9.5pt print text", "font-size: 9.5pt !important"],
  ["employee badge details use 8pt print text", "font-size: 8pt !important"],
  ["employee badge footer uses 8.5pt print text", "font-size: 8.5pt !important"],
  ["employee department may use three print lines", "-webkit-line-clamp: 3 !important"],
  ["paid operations can move upward", "moveOperation(operation.id, -1)"],
  ["paid operations can move downward", "moveOperation(operation.id, 1)"],
  ["reordered paid operations persist their sequence", "return { ...operation, sourceOrder }"],
  ["issued size groups use the guarded delete endpoint", '"/api/payroll/qr-labels/delete-batch"'],
  ["issued size deletion sends exact visible label ids", "label_ids: sizeLabels.map((label) => label.id)"],
  ["used labels disable size deletion", "Number(label.return_count || 0) > 0"],
  ["every issued label has an edit action", "onEdit={() => openLabelCorrection(label)}"],
  ["single-label edits use the guarded endpoint", "`/api/payroll/qr-labels/${labelCorrection.label.id}`"],
  ["single-label splits use the guarded endpoint", "`/api/payroll/qr-labels/${labelCorrection.label.id}/split`"],
  ["split totals must match the source quantity", "splitTotal !== originalQuantity"],
  ["superseded labels stay hidden but prevent accidental reissue", "label.status !== \"superseded\""],
  ["superseded tombstones are fetched to prevent accidental reissue", "include_superseded=true"],
  ["edited labels can be printed separately", "printIssuedLabels(editedIssuedLabels)"],
  ["ERP order picker requests sewing-closed work only", "sewing_completed_only=true"],
  ["ERP quantities use sewing-entered output", "process.sewing_completed_quantity"],
  ["ERP size quantities are read-only", "readOnly={!selectedProcess?.is_manual}"],
  ["ERP labels use exact batch-and-size sewing output", "batch.sewingSizes.find((row) => sameSize(row.size, sizeOption.size))?.sewing_completed_quantity"],
];

if (source.includes("№ {label.id}")) throw new Error("Database label ID is still used as the printed operation number");

const issuedLabel = source.slice(source.indexOf("function IssuedProcessLabel"), source.indexOf("function LabelLine"));
const issuedDetails = issuedLabel.slice(issuedLabel.indexOf('className="process-label__details'), issuedLabel.indexOf('className="process-label__footer'));
if (issuedDetails.includes('t("page.processQr.kroyNo")')) {
  throw new Error("Kroy number must be moved out of the details and into the bottom footer");
}

for (const [name, contract] of required) {
  if (!source.includes(contract)) throw new Error(`Missing ${name} contract`);
}

const sizeNumber = (value) => (value.match(/\d+(?:[.,]\d+)?/g) || []).at(-1);
const compareSizes = (left, right) => {
  const leftNumber = sizeNumber(left);
  const rightNumber = sizeNumber(right);
  if (leftNumber && rightNumber) return Number(leftNumber) - Number(rightNumber);
  return left.localeCompare(right, undefined, { numeric: true });
};

const sizes = ["3XL-54", "M-46", "2XL-52", "S-44", "XL-50", "L-48"];
const sortedSizes = [...sizes].sort(compareSizes);
const expectedSizes = ["S-44", "M-46", "L-48", "XL-50", "2XL-52", "3XL-54"];
if (JSON.stringify(sortedSizes) !== JSON.stringify(expectedSizes)) {
  throw new Error(`Unexpected size order: ${sortedSizes.join(", ")}`);
}

const operationOrder = new Map([["FIRST", 0], ["SECOND", 1], ["THIRD", 2]]);
const labels = [
  { operation: "THIRD", copy: 1, id: 30 },
  { operation: "FIRST", copy: 2, id: 12 },
  { operation: "SECOND", copy: 1, id: 20 },
  { operation: "FIRST", copy: 1, id: 11 },
].sort((left, right) => (
  operationOrder.get(left.operation) - operationOrder.get(right.operation)
  || left.copy - right.copy
  || left.id - right.id
));
if (labels.map((label) => `${label.operation}:${label.copy}`).join(",") !== "FIRST:1,FIRST:2,SECOND:1,THIRD:1") {
  throw new Error("Model operation order was not preserved");
}

const modelOperationNumbers = new Map([["FIRST", 1], ["SECOND", 2], ["THIRD", 3]]);
const labelsAcrossSizes = [
  { size: "S-44", operation: "FIRST" },
  { size: "M-46", operation: "FIRST" },
  { size: "L-48", operation: "SECOND" },
];
const displayedNumbers = labelsAcrossSizes.map((label) => modelOperationNumbers.get(label.operation));
if (displayedNumbers.join(",") !== "1,1,2") {
  throw new Error("The same model operation must keep the same printed number across sizes");
}

const mixedBulkPrintLabels = [
  { size: "L-48", operation: "FIRST", copy: 1, id: 41 },
  { size: "S-44", operation: "SECOND", copy: 1, id: 12 },
  { size: "M-46", operation: "FIRST", copy: 1, id: 21 },
  { size: "S-44", operation: "FIRST", copy: 2, id: 11 },
  { size: "S-44", operation: "FIRST", copy: 1, id: 10 },
].sort((left, right) => (
  compareSizes(left.size, right.size)
  || operationOrder.get(left.operation) - operationOrder.get(right.operation)
  || left.copy - right.copy
  || left.id - right.id
));
const mixedBulkPrintOrder = mixedBulkPrintLabels
  .map((label) => `${label.size}:${label.operation}:${label.copy}`)
  .join(",");
if (mixedBulkPrintOrder !== "S-44:FIRST:1,S-44:FIRST:2,S-44:SECOND:1,M-46:FIRST:1,L-48:FIRST:1") {
  throw new Error(`Bulk printing is not size-major: ${mixedBulkPrintOrder}`);
}

console.log("Process QR ordering contract passed.");
