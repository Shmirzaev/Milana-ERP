import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(new URL("../src/app/(app)/forecasting/page.tsx", import.meta.url), "utf8");
const brandedStart = page.indexOf("{branded.map((row: any) => (");
const reorderStart = page.indexOf("{reorder.map((row: any) => (");
const reorderEnd = page.indexOf("{reorder.length === 0", reorderStart);
assert.ok(brandedStart >= 0 && reorderStart > brandedStart && reorderEnd > reorderStart);

const brandedRows = page.slice(brandedStart, reorderStart);
const reorderRows = page.slice(reorderStart, reorderEnd);
assert.match(brandedRows, /onClick=\{\(\) => saveSuggestion\(row\)\}/);
assert.match(page, /if \(!canManage \|\| !row\.model_id\) return;/);
assert.match(page, /item_reorder_suggestions \|\| \[\]\)\.filter\(\(row: any\) => Boolean\(row\.model_id\)\)/);
assert.match(reorderRows, /canManage && \(row\.model_id \?/);
assert.match(reorderRows, /page\.forecasting\.unassignedSaveUnavailable/);
assert.match(reorderRows, /page\.forecasting\.openInventory/);
assert.match(page, /page\.forecasting\.sharedInventoryExcluded/);
assert.doesNotMatch(page, /cards\.reorder_alert_count/);

const key = '"page.forecasting.unassignedSaveUnavailable"';
const localeFiles = ["en-base.ts", "ru-base.ts", "uz-base.ts"];
for (const localeFile of localeFiles) {
  const locale = await readFile(new URL(`../src/lib/i18n/locales/${localeFile}`, import.meta.url), "utf8");
  assert.equal(locale.split(key).length - 1, 1, `${localeFile} must translate the unavailable state`);
  const supplemental = await readFile(new URL(`../src/lib/i18n/locales/${localeFile.replace("-base", "-supplemental")}`, import.meta.url), "utf8");
  assert.equal(supplemental.split('"page.forecasting.sharedInventoryExcluded"').length - 1, 1);
}

console.log("forecasting reorder save scope: ok");
