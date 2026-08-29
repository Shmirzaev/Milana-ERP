import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(new URL("../src/app/(app)/forecasting/page.tsx", import.meta.url), "utf8");
const chart = await readFile(new URL("../src/components/ForecastLineChart.tsx", import.meta.url), "utf8");
const dictionary = await readFile(new URL("../src/lib/i18n/dict.ts", import.meta.url), "utf8");
const localeFiles = await Promise.all(
  ["en-base.ts", "ru-base.ts", "uz-base.ts"].map((name) => (
    readFile(new URL(`../src/lib/i18n/locales/${name}`, import.meta.url), "utf8").catch(() => null)
  )),
);

assert.match(page, /data\?\.demand_trend/);
assert.equal((page.match(/<ForecastLineChart/g) || []).length, 2);
assert.match(page, /projected: Number\(row\.projected_demand/);
assert.match(page, /available: Number\(row\.available_quantity/);
assert.match(page, /suggested: Number\(row\.suggested_quantity/);
assert.match(chart, /role="img"/);
assert.match(chart, /<table className="sr-only">/);
assert.doesNotMatch(chart, /gradient|shadow-xl|shadow-2xl|rounded-2xl|rounded-3xl/);

for (const key of [
  "page.forecasting.weeklyDemand",
  "page.forecasting.variantCoverage",
  "page.forecasting.availableStock",
  "page.forecasting.suggestedProduction",
  "page.forecasting.noChartData",
]) {
  assert.equal((dictionary.match(new RegExp(`"${key.replaceAll(".", "\\.")}"`, "g")) || []).length, 3, `${key} must exist in EN/RU/UZ`);
  if (localeFiles.every(Boolean)) {
    for (const locale of localeFiles) {
      assert.match(locale, new RegExp(`"${key.replaceAll(".", "\\.")}"`), `${key} must exist in each runtime locale`);
    }
  }
}

console.log("forecasting chart contract: ok");
