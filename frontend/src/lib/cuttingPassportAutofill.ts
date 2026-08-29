export type CuttingPassportAutofillSource = {
  layer_weight_kg?: number | null;
  total_layers?: number | null;
  planned_kg?: number | null;
  pieces?: number | null;
  rolls_count?: number | null;
  scrap_kg?: number | null;
  waste_pct?: number | null;
  operator_name?: string | null;
  operator_name_manual?: string | null;
  total_beka_kg?: number | null;
  other_beka_kg?: number | null;
  notes?: string | null;
};

export type CuttingPassportAutofillValues = {
  input_quantity?: number;
  layer_material_kg?: number;
  material_rolls_used?: number;
  layup_operator_name?: string;
  cut_pieces?: number;
  notes?: string;
};

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function nonNegativeNumber(value: unknown): number | null {
  const parsed = finiteNumber(value);
  return parsed !== null && parsed >= 0 ? parsed : null;
}

function positiveNumber(value: unknown): number | null {
  const parsed = finiteNumber(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function roundKg(value: number): number {
  return Number(value.toFixed(3));
}

export function primaryMaterialKgFromPassport(
  passport: CuttingPassportAutofillSource | null | undefined,
): number | null {
  if (!passport) return null;
  const layerWeight = positiveNumber(passport.layer_weight_kg);
  const totalLayers = positiveNumber(passport.total_layers);
  const scrapKg = nonNegativeNumber(passport.scrap_kg) ?? 0;
  if (layerWeight !== null && totalLayers !== null) {
    return roundKg(layerWeight * totalLayers + scrapKg);
  }
  const issuedKg = positiveNumber(passport.planned_kg);
  return issuedKg === null ? null : roundKg(issuedKg);
}

export function wasteKgFromPassport(
  passport: CuttingPassportAutofillSource | null | undefined,
  inputQuantity: number,
): number | null {
  if (!passport) return null;
  const wastePct = positiveNumber(passport.waste_pct);
  const issuedKg = positiveNumber(passport.planned_kg);
  const baseKg = inputQuantity > 0 ? inputQuantity : (issuedKg ?? 0);
  if (wastePct !== null && baseKg > 0) {
    return roundKg(baseKg * wastePct / 100);
  }
  const scrapKg = positiveNumber(passport.scrap_kg);
  return scrapKg === null ? null : roundKg(scrapKg);
}

export function cuttingPassportAutofillValues(
  passport: CuttingPassportAutofillSource | null | undefined,
): CuttingPassportAutofillValues {
  if (!passport) return {};
  const values: CuttingPassportAutofillValues = {};
  const inputQuantity = primaryMaterialKgFromPassport(passport);
  const layerWeight = positiveNumber(passport.layer_weight_kg);
  const rollsCount = nonNegativeNumber(passport.rolls_count);
  const pieces = positiveNumber(passport.pieces);
  const operatorName = String(passport.operator_name || passport.operator_name_manual || "").trim();
  const notes = String(passport.notes || "").trim();

  if (inputQuantity !== null) values.input_quantity = inputQuantity;
  if (layerWeight !== null) values.layer_material_kg = layerWeight;
  if (rollsCount !== null) values.material_rolls_used = rollsCount;
  if (operatorName) values.layup_operator_name = operatorName;
  if (pieces !== null) values.cut_pieces = Math.floor(pieces);
  if (notes) values.notes = notes;
  return values;
}

export function beikaKgFromPassport(
  passport: CuttingPassportAutofillSource | null | undefined,
): number | null {
  if (!passport) return null;
  const quantities = [passport.total_beka_kg, passport.other_beka_kg]
    .map(positiveNumber)
    .filter((quantity): quantity is number => quantity !== null);
  if (quantities.length === 0) return null;
  return roundKg(quantities.reduce((sum, quantity) => sum + quantity, 0));
}
