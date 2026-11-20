export type CuttingBalance = {
  key?: string;
  bundles: number | null;
  pieces: number | null;
  pieces_min: number;
  pieces_max: number;
  adjusted?: boolean;
};

export type CuttingBalanceTotals = CuttingBalance & {
  orders: number;
  work_orders: number;
  unconfirmed_batches: number;
  unresolved_batches: number;
};

export function cuttingPiecesText(balance: Partial<Pick<CuttingBalance, "pieces" | "pieces_min" | "pieces_max">> | undefined): string {
  if (!balance) return "—";
  if (balance.pieces != null) return balance.pieces.toLocaleString();
  if (balance.pieces_min == null || balance.pieces_max == null) return "—";
  return `${balance.pieces_min.toLocaleString()}–${balance.pieces_max.toLocaleString()}`;
}

export function cuttingBundlesText(balance: Partial<Pick<CuttingBalance, "bundles">> | undefined, needsCount: string): string {
  if (!balance || balance.bundles === undefined) return "—";
  return balance.bundles === null ? needsCount : balance.bundles.toLocaleString();
}
