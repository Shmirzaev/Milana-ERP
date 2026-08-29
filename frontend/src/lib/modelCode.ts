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

export function normalizeModelNumber(value: unknown): string {
  return clean(value).replace(/^(\p{L}+)-(?=\d)/u, "$1");
}

const MODEL_CODE_CONFUSABLES: Record<string, string> = {
  А: "a", а: "a",
  В: "b", в: "b",
  Е: "e", е: "e",
  К: "k", к: "k",
  М: "m", м: "m",
  Н: "h", н: "h",
  О: "o", о: "o",
  Р: "p", р: "p",
  С: "c", с: "c",
  Т: "t", т: "t",
  Х: "x", х: "x",
  У: "y", у: "y",
};

export function normalizeModelSearch(value: unknown): string {
  return clean(value)
    .toLocaleLowerCase()
    .replace(/[АаВвЕеКкМмНнОоРрСсТтХхУу]/g, (character) => MODEL_CODE_CONFUSABLES[character] || character)
    .replace(/-/g, "")
    .replace(/\s+/g, " ");
}

export function modelSearchIncludes(value: unknown, query: unknown): boolean {
  const needle = normalizeModelSearch(query);
  return Boolean(needle) && normalizeModelSearch(value).includes(needle);
}

export function buildModelCode(modelNo: string, variantNo: string): string {
  const cleanModelNo = normalizeModelNumber(modelNo);
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
  const configuredModelNo = clean(general.model_no || general.modelNo);
  const configuredVariantNo = clean(general.variant_no || general.variantNo);
  const modelNo = normalizeModelNumber(configuredModelNo || fromCode.modelNo);
  // An explicit model number with no explicit variant is a base model. Its
  // final dash belongs to the model number and must not be reinterpreted as a
  // default variant.
  const variantNo = configuredModelNo
    ? configuredVariantNo
    : configuredVariantNo || fromCode.variantNo;
  return {
    modelNo,
    variantNo,
    code: buildModelCode(modelNo, variantNo) || fromCode.code,
  };
}
