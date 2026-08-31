import fs from "node:fs";
import path from "node:path";

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
