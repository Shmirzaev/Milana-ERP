import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const pagePath = path.join(root, "src/app/(app)/models/[id]/page.tsx");
const source = fs.readFileSync(pagePath, "utf8");
const cuttingPath = path.join(root, "src/app/(app)/work-orders/[id]/cutting/page.tsx");
const cuttingSource = fs.readFileSync(cuttingPath, "utf8");
const errors = [];

function requireSource(fragment, message) {
  if (!source.includes(fragment)) errors.push(message);
}

function requireCuttingSource(fragment, message) {
  if (!cuttingSource.includes(fragment)) errors.push(message);
}

function forbidCuttingSource(fragment, message) {
  if (cuttingSource.includes(fragment)) errors.push(message);
}

requireSource(
  'material_name: string;',
  "The BOM editor must retain a separate manual material name.",
);
requireSource(
  'const isManualUslugaMaterial = isUsluga && target === "material";',
  "Only Usluga fabric rows should use the manual-name flow.",
);
requireSource(
  'payload.material_name = bomRow.material_name.trim();',
  "Usluga fabric saves must send the trimmed manual name.",
);
requireSource(
  'item_id: isManualUslugaMaterial ? null : bomRow.item_id,',
  "Manual Usluga fabrics must not send an inventory item ID.",
);
requireSource(
  'placeholder={t("page.modelDetail.manualFabricName")}',
  "The Usluga fabric editor must render a manual text input.",
);
requireSource(
  'r.material_name || r.item?.name || "-"',
  "BOM readouts must prefer the independent Usluga fabric name.",
);
requireSource(
  'payload.material_role = bomRow.material_role;',
  "Usluga fabrics must save their main or secondary role.",
);
requireSource(
  'router.push(`${modelPageBase}/${createdVariantId}?mode=edit`);',
  "Creating an Usluga variant must move the operator into that new variant before further fabric edits.",
);
requireCuttingSource(
  'model_bom_id: isUsluga ? (form.model_bom_id || null) : null,',
  "Usluga cutting records must identify the selected manual model fabric.",
);
requireCuttingSource(
  'const isSecondaryUslugaFabric = selectedUslugaFabric?.material_role === "secondary";',
  "Cutting must distinguish report-only secondary material batches.",
);
requireCuttingSource(
  'isSecondaryUslugaFabric ? [] : bundles',
  "Secondary fabric records must never create product bundles.",
);
requireCuttingSource(
  'if (isAlreadyBatched && !form.production_batch_id) {',
  "Every batched Usluga material record must require a selected production batch.",
);
requireCuttingSource(
  'production_batch_id: form.production_batch_id || null,',
  "Secondary Usluga material records must persist their selected production batch.",
);
requireCuttingSource(
  '{isAlreadyBatched && (',
  "The production-batch selector must remain visible for secondary Usluga materials.",
);
forbidCuttingSource(
  'isAlreadyBatched && !isSecondaryUslugaFabric',
  "The production-batch selector must not be hidden for secondary Usluga materials.",
);
forbidCuttingSource(
  'production_batch_id: isSecondaryUslugaFabric ? null',
  "Secondary Usluga material records must not discard the selected production batch.",
);
requireCuttingSource(
  '/approve-usluga-batch`, {}',
  "Usluga Planning must have an explicit batch approval action.",
);
requireCuttingSource(
  'api.openLabel(`/api/cutting/records/${row.id}/production-sheet${query}`);',
  "Each main batch must remain independently printable.",
);

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log("Usluga manual fabric UI contract OK");
