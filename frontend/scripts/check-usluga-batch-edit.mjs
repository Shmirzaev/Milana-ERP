import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const pagePath = path.join(root, "src/app/(app)/work-orders/[id]/cutting/page.tsx");
const source = fs.readFileSync(pagePath, "utf8");
const errors = [];

function requireSource(fragment, message) {
  if (!source.includes(fragment)) errors.push(message);
}

requireSource(
  'api.patch(`/api/work-orders/${id}/batches/${batchId}`',
  "ECT Usluga Cutting must save batch-plan edits through the guarded backend route.",
);
requireSource(
  'disabled={batchPlanEditBusy || row.name_editable === false}',
  "The batch-name Edit action must remain available after bundles exist.",
);
requireSource(
  't("batch.lockedAfterBundles")',
  "Rows with bundle evidence must explain that only quantity is locked.",
);
requireSource(
  '...(quantityEditable ? { planned_quantity: quantity } : {})',
  "Locked rows must submit a name-only correction without attempting to change quantity.",
);
requireSource(
  'disabled={!quantityEditable}',
  "The quantity input must remain protected after bundle evidence exists.",
);
requireSource(
  'maxLength={128}',
  "The batch-name input must respect the database length limit.",
);
requireSource(
  'fmtQty(row.layer_material_kg)',
  "Saved layer-material kilograms must remain visible in the Usluga Cutting table.",
);
requireSource(
  'fmtQty(row.beika_kg)',
  "Saved binding kilograms must remain visible in the Usluga Cutting table.",
);
requireSource(
  'fmtQty(row.material_rolls_used)',
  "Saved roll usage must remain visible in the Usluga Cutting table.",
);
requireSource(
  'fmtQty(row.waste_quantity)',
  "Saved waste quantity must remain visible in the Usluga Cutting table.",
);
requireSource(
  'row.layup_operator_name',
  "The saved layup operator must remain visible in the Usluga Cutting table.",
);
requireSource(
  'row.notes &&',
  "Saved Cutting notes must remain visible in the Usluga Cutting table.",
);
requireSource(
  'report_piece_count: isSecondaryUslugaFabric ? numberOrZero(form.report_piece_count) : 0',
  "Secondary-fabric piece counts must be submitted through the report-only field.",
);
requireSource(
  'value={form.report_piece_count}',
  "The Usluga Cutting form must let operators enter report-only pieces for additional fabrics.",
);
requireSource(
  'row.material_role === "secondary" ? row.report_piece_count : row.cut_pieces',
  "The Cutting batch table must show report-only pieces for additional fabrics without replacing main-fabric output.",
);
requireSource(
  't("usluga.reportOnly")',
  "Additional-fabric piece counts must be clearly marked as report-only.",
);
requireSource(
  'api.patch(`/api/cutting/records/${recordId}/usluga-report-pieces`',
  "Saved additional-fabric batches must allow their report-only piece count to be corrected.",
);
requireSource(
  'api.patch(`/api/cutting/records/${recordId}/usluga-size-counts`',
  "Main Usluga batches must save corrected size counts through the guarded endpoint.",
);
requireSource(
  'setEditingUslugaSizeCountsId(Number(row.id))',
  "Main Usluga batch rows with bundles must expose an Edit action.",
);
requireSource(
  'sizeCountEditTotal !== requiredSizeCountTotal',
  "The UI must keep the batch total unchanged while size counts are redistributed.",
);
requireSource(
  't("usluga.sizeCountEditHint")',
  "The editor must explain that bundle identity and history are preserved.",
);

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log("Usluga Cutting batch edit UI contract OK");
