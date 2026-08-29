import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const pagePath = path.join(root, "src", "app", "(app)", "work-orders", "[id]", "cutting", "page.tsx");
const dictionaryPath = path.join(root, "src", "lib", "i18n", "dict.ts");
const page = fs.readFileSync(pagePath, "utf8");
const dictionary = fs.readFileSync(dictionaryPath, "utf8");

const requiredPageFragments = [
  "type CuttingSheetOption = {",
  "const [selectedPrintCuttingRecordId, setSelectedPrintCuttingRecordId] = useState(0);",
  "const printableCuttingSheets = (() => {",
  "aria-label={t(\"page.cutting.selectPrintBatch\")}",
  "setSelectedPrintCuttingRecordId(Number(event.target.value || 0))",
  "`/api/cutting/records/${printableCuttingRecordId}/production-sheet${query}`",
];

for (const fragment of requiredPageFragments) {
  if (!page.includes(fragment)) {
    throw new Error(`Missing cutting-sheet selector contract: ${fragment}`);
  }
}

const translationCount = dictionary.split('"page.cutting.selectPrintBatch"').length - 1;
if (translationCount !== 3) {
  throw new Error(`Expected three cutting-sheet selector translations, found ${translationCount}`);
}

console.log("Cutting-sheet batch selector contract OK");
