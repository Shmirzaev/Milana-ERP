import { modelCodeParts } from "@/lib/modelCode";
import { formatModelComposition } from "@/lib/modelComposition";

export type ModelVariantModel = {
  id: number;
  code?: string | null;
  name?: string | null;
  category?: string | null;
  details_json?: {
    general?: {
      model_no?: string | null;
      modelNo?: string | null;
      variant_no?: string | null;
      variantNo?: string | null;
    } | null;
    translation?: Record<string, string>;
  } | null;
  primary_image_url?: string | null;
  primary_image?: {
    file_url?: string | null;
    file_name?: string | null;
    content_type?: string | null;
  } | null;
  variant_no?: string | null;
  variant_fabric?: string | null;
  variant_picture_url?: string | null;
  fabric?: string | null;
  picture_url?: string | null;
};

export type ModelVariantOption<T extends ModelVariantModel = ModelVariantModel> = {
  id: number;
  key: string;
  model: T;
  modelNo: string;
  variantNo: string;
  code: string;
  name: string;
  category: string;
  fabric: string;
  pictureUrl: string;
};

export type ModelVariantGroup<T extends ModelVariantModel = ModelVariantModel> = {
  key: string;
  modelNo: string;
  name: string;
  category: string;
  representative: T;
  variants: ModelVariantOption<T>[];
};

function clean(value: unknown): string {
  return String(value ?? "").trim();
}

function normalized(value: unknown): string {
  return clean(value).toLowerCase().replace(/\s+/g, " ");
}

function naturalCompare(a: string, b: string): number {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

export function modelVariantNo(model: ModelVariantModel | null | undefined): string {
  return clean(model?.variant_no) || modelCodeParts(model).variantNo;
}

export function modelVariantFabric(model: ModelVariantModel | null | undefined): string {
  return clean(model?.variant_fabric) || clean(model?.fabric) || formatModelComposition(model);
}

export function modelVariantPictureUrl(model: ModelVariantModel | null | undefined): string {
  return clean(model?.variant_picture_url) || clean(model?.picture_url) || clean(model?.primary_image_url) || clean(model?.primary_image?.file_url);
}

export function modelVariantGroupKey(model: ModelVariantModel | null | undefined): string {
  const parts = modelCodeParts(model);
  const modelNo = clean(parts.modelNo);
  if (modelNo) return `model:${normalized(modelNo)}`;
  const name = clean(model?.name);
  if (name) return `name:${normalized(name)}`;
  return `id:${Number(model?.id || 0)}`;
}

export function modelVariantOption<T extends ModelVariantModel>(model: T): ModelVariantOption<T> {
  const parts = modelCodeParts(model);
  const variantNo = modelVariantNo(model);
  return {
    id: Number(model.id),
    key: `${Number(model.id)}:${variantNo || model.code || ""}`,
    model,
    modelNo: clean(parts.modelNo),
    variantNo,
    code: clean(parts.code || model.code),
    name: clean(model.name),
    category: clean(model.category),
    fabric: modelVariantFabric(model),
    pictureUrl: modelVariantPictureUrl(model),
  };
}

function groupName<T extends ModelVariantModel>(variants: ModelVariantOption<T>[]): string {
  const counts = new Map<string, { value: string; count: number }>();
  for (const variant of variants) {
    if (!variant.name) continue;
    const key = normalized(variant.name);
    const current = counts.get(key);
    if (current) current.count += 1;
    else counts.set(key, { value: variant.name, count: 1 });
  }
  const names = Array.from(counts.values());
  names.sort((a, b) => b.count - a.count || a.value.length - b.value.length || naturalCompare(a.value, b.value));
  return names[0]?.value || variants[0]?.name || "";
}

export function groupModelVariants<T extends ModelVariantModel>(models: T[] | null | undefined): ModelVariantGroup<T>[] {
  const grouped = new Map<string, ModelVariantOption<T>[]>();
  for (const model of models || []) {
    const option = modelVariantOption(model);
    const key = modelVariantGroupKey(model);
    const rows = grouped.get(key);
    if (rows) rows.push(option);
    else grouped.set(key, [option]);
  }

  return Array.from(grouped.entries())
    .map(([key, variants]) => {
      variants.sort((a, b) => naturalCompare(a.variantNo || a.code, b.variantNo || b.code));
      const first = variants[0] as ModelVariantOption<T>;
      const representative = first.model;
      return {
        key,
        modelNo: first.modelNo,
        name: groupName(variants),
        category: variants.find((variant) => variant.category)?.category || "",
        representative,
        variants,
      };
    })
    .sort((a, b) => naturalCompare(a.modelNo || a.name, b.modelNo || b.name));
}

export function modelGroupLabel(group: ModelVariantGroup): string {
  const code = clean(group.modelNo || group.representative.code);
  return code && group.name ? `${code} - ${group.name}` : code || group.name;
}

export function modelVariantLabel(variant: ModelVariantOption): string {
  const base = clean(variant.variantNo || variant.code || `#${variant.id}`);
  return variant.fabric ? `${base} - ${variant.fabric}` : base;
}

export function modelOrderLabel(model: ModelVariantModel | null | undefined): string {
  if (!model) return "";
  const groupLabel = modelGroupLabel({
    key: modelVariantGroupKey(model),
    modelNo: modelCodeParts(model).modelNo,
    name: clean(model.name),
    category: clean(model.category),
    representative: model,
    variants: [modelVariantOption(model)],
  });
  const variant = modelVariantLabel(modelVariantOption(model));
  return variant ? `${groupLabel} / ${variant}` : groupLabel;
}
