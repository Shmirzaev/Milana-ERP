import fs from "node:fs";

const page = fs.readFileSync("src/app/(app)/shipments/page.tsx", "utf8");
const workspace = fs.readFileSync("src/components/ShipmentPreparationWorkspace.tsx", "utf8");

for (const token of [
  "ShipmentPreparationWorkspace",
  "/api/shipments/${activeShipmentId}/preparation",
  "historyQuery",
  "max-w-[1440px]",
]) {
  if (!page.includes(token)) throw new Error(`Shipments page is missing ${token}`);
}

for (const token of [
  "model_image_url",
  "variant_image_url",
  "itemsToPrepare",
  "packageChecklist",
  "storageLocation",
  "waitingForScan",
]) {
  if (!workspace.includes(token)) throw new Error(`Shipment workspace is missing ${token}`);
}

for (const banned of ["rounded-2xl", "rounded-3xl", "shadow-xl", "shadow-2xl", "tracking-[0.18em]"]) {
  if (workspace.includes(banned) || page.includes(banned)) {
    throw new Error(`Shipment workspace uses banned UI class ${banned}`);
  }
}

const backendPath = "../backend/app/api/routes/shipments.py";
if (fs.existsSync(backendPath)) {
  const backend = fs.readFileSync(backendPath, "utf8");
  for (const token of [
    '@router.get("/{sid}/preparation")',
    '"model_image_url"',
    '"variant_image_url"',
    '"location"',
    '"scanned"',
  ]) {
    if (!backend.includes(token)) throw new Error(`Shipment preparation API is missing ${token}`);
  }
}

for (const language of ["en", "ru", "uz"]) {
  const locale = fs.readFileSync(`src/lib/i18n/locales/${language}-supplemental.ts`, "utf8");
  for (const key of [
    "page.shipments.itemsToPrepare",
    "page.shipments.variantPicture",
    "page.shipments.packageChecklist",
    "page.shipments.history",
  ]) {
    if (!locale.includes(`"${key}"`)) throw new Error(`${language} locale is missing ${key}`);
  }
}

console.log("Shipment preparation workspace contract OK");
