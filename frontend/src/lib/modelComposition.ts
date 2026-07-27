import { formatComposition, type MaterialComposition } from "@/lib/materialComposition";

function rowsFrom(value: unknown): MaterialComposition[] {
  return Array.isArray(value) ? value : [];
}

export function modelCompositionRows(model?: any): MaterialComposition[] {
  return rowsFrom(
    model?.details_json?.composition
      ?? model?.details?.composition
      ?? model?.composition
      ?? null,
  );
}

export function formatModelComposition(model?: any, fallback?: MaterialComposition[] | null): string {
  return (
    formatComposition(modelCompositionRows(model))
    || formatComposition(fallback)
    || formatComposition(model?.material_composition)
  );
}
