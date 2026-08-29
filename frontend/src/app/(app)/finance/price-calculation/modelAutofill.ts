import { modelCodeParts } from "@/lib/modelCode";
import { FIXED_PACKAGING_COST, type EditableField, type PriceCalculationRow } from "./priceCalculation";

type ModelBomItem = {
  sku?: string | null;
  name?: string | null;
  category?: string | null;
  default_cost?: number | string | null;
};

type ModelBomRow = {
  item?: ModelBomItem | null;
  quantity_per_piece?: number | string | null;
  waste_percent?: number | string | null;
  unit?: string | null;
};

export type PriceCalculationModelDetail = {
  id: number;
  code?: string | null;
  name?: string | null;
  category?: string | null;
  product_type?: string | null;
  primary_image_url?: string | null;
  variant_picture_url?: string | null;
  primary_image?: {
    file_url?: string | null;
  } | null;
  details_json?: {
    general?: {
      model_no?: string | null;
      modelNo?: string | null;
      variant_no?: string | null;
      variantNo?: string | null;
    } | null;
    translation?: Partial<Record<"en" | "ru" | "uz", string>> | null;
    costing?: {
      labor_pct?: number | string | null;
      target_margin_pct?: number | string | null;
    } | null;
  } | null;
  sizes?: Array<{ size?: string | null }> | null;
  bom?: ModelBomRow[] | null;
};

export const MODEL_AUTOFILL_FIELDS: EditableField[] = [
  "modelNo",
  "variantNo",
  "modelCategory",
  "modelName",
  "modelSize",
  "bindingKgPerPiece",
  "fabricPrice",
  "sewingCost",
  "accessory1",
  "accessory2",
  "accessory3",
  "accessory4",
  "profitPercentage",
];

function clean(value: unknown): string {
  return String(value ?? "").trim();
}

function number(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function numberText(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "";
  return String(Number(value.toFixed(4)));
}

function bomCost(row: ModelBomRow): number {
  const requiredPerPiece = number(row.quantity_per_piece) * (1 + number(row.waste_percent) / 100);
  return requiredPerPiece * number(row.item?.default_cost);
}

function isBindingRow(row: ModelBomRow): boolean {
  const category = clean(row.item?.category).toLowerCase();
  const identity = `${clean(row.item?.sku)} ${clean(row.item?.name)}`.toLowerCase();
  return category === "semi_finished"
    || /binding|ribana|rib knit|ribbed|beyka|бейк|кашкор|манжет|yoqa|tasma/.test(identity);
}

export function modelAutofillValues(
  model: PriceCalculationModelDetail,
  lang: "en" | "ru" | "uz",
): Partial<PriceCalculationRow> {
  const codeParts = modelCodeParts(model);
  const bom = model.bom || [];
  const primaryFabric = bom.find((row) => clean(row.item?.category).toLowerCase() === "fabric")
    || bom.find((row) => clean(row.item?.category).toLowerCase() === "semi_finished");
  const binding = bom.find((row) => row !== primaryFabric && isBindingRow(row));
  const accessoryCosts = bom
    .filter((row) => clean(row.item?.category).toLowerCase() === "accessory")
    .map(bomCost)
    .filter((cost) => cost > 0)
    .slice(0, 4);
  const baseBomCost = bom.reduce((sum, row) => sum + bomCost(row), 0);
  const laborPercentage = number(model.details_json?.costing?.labor_pct);
  const targetMargin = number(model.details_json?.costing?.target_margin_pct);
  const sizes = Array.from(new Set(
    (model.sizes || []).map((row) => clean(row.size)).filter(Boolean),
  ));

  return {
    modelNo: clean(codeParts.modelNo),
    variantNo: clean(codeParts.variantNo),
    modelCategory: clean(model.category) || clean(model.product_type),
    modelName: clean(model.details_json?.translation?.[lang]) || clean(model.name),
    modelSize: sizes.join(", "),
    bindingKgPerPiece: binding ? numberText(number(binding.quantity_per_piece) * (1 + number(binding.waste_percent) / 100)) : "",
    fabricPrice: primaryFabric ? numberText(number(primaryFabric.item?.default_cost)) : "",
    sewingCost: laborPercentage > 0 && baseBomCost > 0
      ? numberText(baseBomCost * laborPercentage / 100)
      : "",
    accessory1: numberText(accessoryCosts[0] || 0),
    accessory2: numberText(accessoryCosts[1] || 0),
    accessory3: numberText(accessoryCosts[2] || 0),
    accessory4: numberText(accessoryCosts[3] || 0),
    profitPercentage: numberText(targetMargin),
  };
}

export function applyModelAutofill(
  row: PriceCalculationRow,
  values: Partial<PriceCalculationRow>,
): PriceCalculationRow {
  const cleared = Object.fromEntries(MODEL_AUTOFILL_FIELDS.map((field) => [field, ""])) as Partial<PriceCalculationRow>;
  return { ...row, ...cleared, ...values, packagingCost: String(FIXED_PACKAGING_COST) };
}
