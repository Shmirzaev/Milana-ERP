export type MaterialComposition = {
  name?: string | null;
  percentage?: number | string | null;
};

export function formatComposition(rows?: MaterialComposition[] | null): string {
  const parts = (rows || [])
    .map((row) => {
      const name = String(row?.name || "").trim();
      const percentage = Number(row?.percentage || 0);
      if (!name || !Number.isFinite(percentage) || percentage <= 0) return "";
      return `${name} ${percentage.toLocaleString(undefined, { maximumFractionDigits: 2 })}%`;
    })
    .filter(Boolean);
  return parts.join(", ");
}

export function compositionTotal(rows?: MaterialComposition[] | null): number {
  return (rows || []).reduce((sum, row) => {
    const percentage = Number(row?.percentage || 0);
    return Number.isFinite(percentage) ? sum + percentage : sum;
  }, 0);
}
