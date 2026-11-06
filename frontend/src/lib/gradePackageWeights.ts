export type PackagingGrade = "first_grade" | "second_grade";

/** Distribute entered total kg in exact 0.0001 kg units, weighted by pieces. */
export function gradePackageWeights(grade: PackagingGrade, rows: { size: string; quantity: number }[], totalKg: string) {
  if (!/^\d{1,10}(?:\.\d{1,4})?$/.test(totalKg.trim())) throw new Error("weight");
  const [whole, fraction = ""] = totalKg.trim().split(".");
  const units = Number(whole) * 10000 + Number(fraction.padEnd(4, "0"));
  if (!Number.isSafeInteger(units) || units <= 0 || units > 99999999999999) throw new Error("weight");
  if (rows.some(row => !Number.isSafeInteger(row.quantity) || row.quantity < 0)) throw new Error("quantity");
  const pieces = rows.reduce((sum, row) => sum + row.quantity, 0);
  const count = grade === "first_grade" ? pieces : rows.filter(row => row.quantity > 0).length;
  if (!Number.isSafeInteger(pieces) || pieces < 1 || count > 200) throw new Error("quantity");
  // Every piece has a positive representable share; no zero-weight labels.
  if (units < pieces) throw new Error("weight");
  const perPiece = Math.floor(units / pieces);
  let remaining = units % pieces;
  return rows.flatMap(row => Array.from({ length: grade === "first_grade" ? row.quantity : Number(row.quantity > 0) }, () => {
    const quantity = grade === "first_grade" ? 1 : row.quantity;
    const extra = Math.min(quantity, remaining);
    remaining -= extra;
    return { size: row.size, quantity, weight_kg: (perPiece * quantity + extra) / 10000 };
  }));
}
