import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => readFileSync(path.join(root, relative), "utf8");
const planning = read("src/app/(app)/planning/page.tsx");
const cutting = read("src/app/(app)/work-orders/[id]/cutting/page.tsx");

for (const token of [
  "addBrandedMaterial",
  "page.planning.addFabric",
  "materials: materials.map",
  "page.planning.duplicateFabric",
]) {
  if (!planning.includes(token)) throw new Error(`Planning multi-material contract missing: ${token}`);
}

for (const token of [
  "plannedMaterials",
  "page.cutting.materialUsage",
  "page.cutting.enterEveryMaterialAmount",
  "materials: normalizedMaterials",
]) {
  if (!cutting.includes(token)) throw new Error(`Cutting multi-material contract missing: ${token}`);
}

for (const language of ["en", "ru", "uz"]) {
  const locale = read(`src/lib/i18n/locales/${language}-base.ts`);
  for (const key of [
    "page.planning.addFabric",
    "page.planning.selectEveryFabric",
    "page.cutting.materialUsage",
    "page.cutting.actualAmountUsed",
  ]) {
    if (!locale.includes(`"${key}"`)) throw new Error(`${language} locale missing: ${key}`);
  }
}

console.log("Multi-material Planning and Cutting UI contract passed.");
