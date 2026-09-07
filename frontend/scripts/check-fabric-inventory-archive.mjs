import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import vm from "node:vm";
import ts from "typescript";

const root = process.cwd();
const inventoryPage = fs.readFileSync(path.join(root, "src/app/(app)/inventory/page.tsx"), "utf8");
const archivePage = fs.readFileSync(path.join(root, "src/app/(app)/inventory/archive/page.tsx"), "utf8");

const checks = [
  [inventoryPage.includes('href="/inventory/archive"'), "Fabric inventory must link to the archive"],
  [archivePage.includes('archived: "true"'), "Archive page must request archived batches only"],
  [archivePage.includes('group: "materials"'), "Archive page must stay scoped to fabric/material batches"],
  [archivePage.includes("archive_reason"), "Archive page must show why each batch was archived"],
  [archivePage.includes("received_quantity") && archivePage.includes("used_quantity"), "Archive page must show quantity history"],
];

const failures = checks.filter(([passed]) => !passed).map(([, message]) => message);
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log("Fabric inventory archive contract passed.");

function loadModule(relativePath, imports = {}) {
  const source = fs.readFileSync(path.join(root, relativePath), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
  const context = { exports: {}, URLSearchParams, require: (name) => {
    assert.ok(name in imports, `Unexpected runtime import: ${name}`);
    return imports[name];
  } };
  vm.runInNewContext(compiled, context);
  return context.exports;
}
const access = loadModule("src/lib/access.ts");
const pricing = loadModule("src/lib/priceCalculationRequests.ts", { "@/lib/access": access });
const storage = { department_code: "STR", permissions: ["storage.items", "storage.receive"] };
const materialOnly = { ...storage, permissions: [...storage.permissions, "inventory.materials_only", "price_calculation.accessories"] };
assert.equal(pricing.isAccessoryPricingUser(storage), true);
assert.equal(pricing.isAccessoryPricingUser(materialOnly), false);
for (const route of ["/inventory?group=accessories", "/inventory/receive?group=accessories", "/inventory/accessory-pricing"]) {
  assert.equal(access.hasInventoryPathAccess(materialOnly, route), false, route);
  assert.equal(access.hasInventoryPathAccess(storage, route), true, route);
}
for (const route of ["/inventory?group=materials", "/inventory/archive", "/inventory/receive?group=materials", "/inventory/master-data", "/shipments"]) {
  assert.equal(access.hasInventoryPathAccess(materialOnly, route), true, route);
}
for (const locale of ["en", "ru", "uz"]) {
  const source = fs.readFileSync(path.join(root, `src/lib/i18n/locales/${locale}-supplemental.ts`), "utf8");
  for (const key of ["restoreBatch", "restoreHelp", "restoreQuantity", "restoreReason", "restoreSuccess", "restoreFailed"]) {
    assert.ok(source.includes(`"page.inventory.${key}"`), `${locale}: ${key}`);
  }
}
console.log("Material-only navigation/pricing and restore locales passed.");
