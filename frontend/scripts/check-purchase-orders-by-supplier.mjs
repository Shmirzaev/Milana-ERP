import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const receivingPage = readFileSync(new URL("../src/app/(app)/purchasing/receiving/page.tsx", import.meta.url), "utf8");
const combinedDictionary = readFileSync(new URL("../src/lib/i18n/dict.ts", import.meta.url), "utf8");

assert.match(receivingPage, /const supplierOrderGroups = useMemo/);
assert.match(receivingPage, /line\.supplier_id \|\| order\.supplier_id/);
assert.match(receivingPage, /line\.supplier_name \|\| order\.supplier_name/);
assert.match(receivingPage, /isKilogramUnit\(line\.unit\)/);
assert.match(receivingPage, /totalOrderedKg \+= Number\(line\.ordered_quantity/);
assert.match(receivingPage, /supplierOrderGroups\.map\(\(group\) =>/);
assert.match(receivingPage, /<Fragment key=\{group\.key\}>/);
assert.match(receivingPage, /page\.purchasing\.supplierTotalOrderedKg/);
assert.match(receivingPage, /fmtQty\(group\.totalOrderedKg\)\} kg/);
assert.match(receivingPage, /const \[collapsedSuppliers, setCollapsedSuppliers\]/);
assert.match(receivingPage, /function toggleSupplierGroup\(supplierKey: string\)/);
assert.match(receivingPage, /aria-expanded=\{!isCollapsed\}/);
assert.match(receivingPage, /aria-controls=\{groupContentId\}/);
assert.match(receivingPage, /<tbody id=\{groupContentId\} hidden=\{isCollapsed\}>/);
assert.match(receivingPage, /isCollapsed \? <ChevronRight/);
assert.doesNotMatch(receivingPage, /openOrders\.flatMap/);
assert.doesNotMatch(receivingPage, /max=\{Number\(receiveState\.line\.remaining_quantity/);
assert.match(receivingPage, /const dialogs = useDialogs\(\)/);
assert.match(receivingPage, /remainingQuantity > 0\.000001/);
assert.match(receivingPage, /await dialogs\.ask\(/);
assert.match(receivingPage, /close_order: closeOrder/);
assert.match(receivingPage, /target="_blank"/);
assert.match(receivingPage, /rel="noopener noreferrer"/);
assert.match(receivingPage, /page\.purchasing\.openPhoto/);

for (const key of [
  "page.purchasing.unassignedSupplier",
  "page.purchasing.supplierTotalOrderedKg",
  "page.purchasing.collapseSupplier",
  "page.purchasing.expandSupplier",
  "page.purchasing.closeShortReceiptTitle",
  "page.purchasing.closeShortReceiptMessage",
  "page.purchasing.closeShortReceiptConfirm",
  "page.purchasing.closeShortReceiptKeepOpen",
  "page.purchasing.openPhoto",
]) {
  const matches = combinedDictionary.split(`"${key}"`).length - 1;
  assert.equal(matches, 3, `${key} must exist in English, Russian, and Uzbek dictionaries`);
}

for (const locale of ["en", "ru", "uz"]) {
  const localeUrl = new URL(`../src/lib/i18n/locales/${locale}-base.ts`, import.meta.url);
  if (!existsSync(localeUrl)) continue;
  const localeDictionary = readFileSync(localeUrl, "utf8");
  assert.match(localeDictionary, /"page\.purchasing\.unassignedSupplier"/);
  assert.match(localeDictionary, /"page\.purchasing\.supplierTotalOrderedKg"/);
  assert.match(localeDictionary, /"page\.purchasing\.collapseSupplier"/);
  assert.match(localeDictionary, /"page\.purchasing\.expandSupplier"/);
  assert.match(localeDictionary, /"page\.purchasing\.closeShortReceiptTitle"/);
  assert.match(localeDictionary, /"page\.purchasing\.closeShortReceiptMessage"/);
  assert.match(localeDictionary, /"page\.purchasing\.closeShortReceiptConfirm"/);
  assert.match(localeDictionary, /"page\.purchasing\.closeShortReceiptKeepOpen"/);
  assert.match(localeDictionary, /"page\.purchasing\.openPhoto"/);
}

console.log("Active purchase orders supplier grouping contract passed.");
