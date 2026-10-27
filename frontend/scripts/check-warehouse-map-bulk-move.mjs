import { readFile } from "node:fs/promises";

const page = await readFile(new URL("../src/app/(app)/warehouse-map/page.tsx", import.meta.url), "utf8");
const dictionary = await readFile(new URL("../src/lib/i18n/dict.ts", import.meta.url), "utf8");

const checks = [
  [page.includes("const [selectedPackageIds, setSelectedPackageIds]"), "warehouse map keeps a multi-package selection"],
  [page.includes('type="checkbox"') && page.includes("togglePackageSelection"), "packages are rendered with checkboxes"],
  [page.includes("selectAllPackages") && page.includes("clearPackageSelection"), "select-all and clear-selection actions exist"],
  [page.includes('api.post("/api/packages/batch/place-on-map"'), "multi-package moves use the batch placement endpoint"],
  [page.includes("package_ids: packagesToMove.map((row) => row.id)"), "every selected package id is sent to the batch endpoint"],
  [page.includes("targetModels.size > 1"), "mixed-model protection considers all selected and destination packages"],
  [page.includes("setMoveSources([])"), "bulk move state is cleared after success or cancellation"],
];

for (const key of [
  "page.warehouseMap.moveSelected",
  "page.warehouseMap.selectAllPackages",
  "page.warehouseMap.clearPackageSelection",
  "page.warehouseMap.selectedPackages",
  "page.warehouseMap.bulkMoveArmed",
  "page.warehouseMap.bulkMovePending",
  "page.warehouseMap.bulkMoveSuccess",
]) {
  const occurrences = dictionary.split(`"${key}"`).length - 1;
  checks.push([occurrences === 3, `${key} is translated in English, Russian, and Uzbek`]);
}

const failed = checks.filter(([ok]) => !ok).map(([, message]) => message);
if (failed.length) {
  throw new Error(`Warehouse map bulk-move contract failed:\n- ${failed.join("\n- ")}`);
}

console.log(`Warehouse map bulk-move contract passed (${checks.length} checks).`);
