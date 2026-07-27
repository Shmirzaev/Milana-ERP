type ModelCodeSource = {
  code?: string | null;
  details_json?: {
    general?: {
      model_no?: string | null;
      modelNo?: string | null;
      variant_no?: string | null;
      variantNo?: string | null;
    } | null;
  } | null;
};

export type ModelCodeParts = {
  modelNo: string;
  variantNo: string;
  code: string;
};

function clean(value: unknown): string {
  return String(value ?? "").trim();
}

export function buildModelCode(modelNo: string, variantNo: string): string {
  const cleanModelNo = clean(modelNo);
  const cleanVariantNo = clean(variantNo);
  if (cleanModelNo && cleanVariantNo) return `${cleanModelNo}-${cleanVariantNo}`;
  return cleanModelNo || cleanVariantNo;
}

export function splitModelCode(code: string | null | undefined): ModelCodeParts {
  const cleanCode = clean(code);
  const dashIndex = cleanCode.lastIndexOf("-");
  if (dashIndex > 0 && dashIndex < cleanCode.length - 1) {
    return {
      modelNo: cleanCode.slice(0, dashIndex),
      variantNo: cleanCode.slice(dashIndex + 1),
      code: cleanCode,
    };
  }
  return { modelNo: cleanCode, variantNo: "", code: cleanCode };
}

export function modelCodeParts(model: ModelCodeSource | null | undefined): ModelCodeParts {
  const fromCode = splitModelCode(model?.code);
  const general = model?.details_json?.general || {};
  const modelNo = clean(general.model_no || general.modelNo || fromCode.modelNo);
  const variantNo = clean(general.variant_no || general.variantNo || fromCode.variantNo);
  return {
    modelNo,
    variantNo,
    code: buildModelCode(modelNo, variantNo) || fromCode.code,
  };
}
