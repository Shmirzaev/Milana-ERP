import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const pagePath = path.join(root, "src/app/(app)/models/[id]/page.tsx");
const source = fs.readFileSync(pagePath, "utf8");
const errors = [];

function requireSource(fragment, message) {
  if (!source.includes(fragment)) errors.push(message);
}

function rejectSource(fragment, message) {
  if (source.includes(fragment)) errors.push(message);
}

rejectSource("variant-fabric-item", "Variants form still renders a fabric/material chooser.");
rejectSource("variantForm.fabric_item_id", "Variants form still stores a selectable fabric item.");
rejectSource("payload.fabric_item_id", "Variants form still sends a variant-specific fabric item.");
requireSource('id="variant-material-color"', "Variants form must retain the optional color field.");
requireSource('id="variant-material-picture"', "Variants form must retain the optional image field.");
rejectSource('readOnly={!editingVariantId}', "The auto-filled variant number must remain editable when creating a variant.");
requireSource(
  'const useAutomaticVariantNumber = !editingVariantId && variantNo === suggestedVariantNo;',
  "The unchanged suggestion must keep using the atomic automatic-number path.",
);
requireSource('if (!useAutomaticVariantNumber)', "A manually edited variant number must be sent to the API.");
requireSource("fabric_item_id?: number | null;", "Variant reads must retain the legacy fabric item field.");
requireSource("{v.fabric || \"-\"}", "Variants table must retain the inherited material readout.");

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log("Model variant form contract OK");
