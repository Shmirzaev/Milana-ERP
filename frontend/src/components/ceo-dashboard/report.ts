import { businessDate, factoryCodes, stageKeys } from "@/components/dashboard/types";

export { businessDate, factoryCodes, stageKeys };
export type { Stage } from "@/components/dashboard/types";
import type { Factory, Stage } from "@/components/dashboard/types";

export const presets = ["today", "yesterday", "thisWeek", "thisMonth", "custom"] as const;
export const groupings = ["daily", "weekly", "monthly"] as const;
export const factories = ["ALL", ...factoryCodes] as const;
export const timezone = "Asia/Tashkent";

export type Preset = typeof presets[number];
export type Grouping = typeof groupings[number];
export type { Factory };
export type FactoryAttribution = Exclude<Factory, "ALL"> | "UNASSIGNED" | "SHARED";
export type DateRange = { start: string; end: string };
export type PieceCounts = { packs: number; pieces: number };
export type Output = { factory: FactoryAttribution; department: string; stage: Stage; pieces: number };

export type ActivityBucket = DateRange & {
  output: Output[];
  finished_receipts: PieceCounts;
  shipments: PieceCounts;
  receipts_unassigned: PieceCounts;
  shipments_unassigned: PieceCounts;
  legacy_imports: PieceCounts;
};

export type BalanceBucket = DateRange & (
  | { status: "unavailable"; as_of: null; values: null }
  | { status: "current" | "snapshot"; as_of: string; values: BalanceValues }
);

type WarehouseCounts = PieceCounts & { available_pieces: number; reserved_pieces: number };
type MaterialCounts = { unit: string; quantity: string; active_batches: number; varieties: number };

export type BalanceValues = {
  waiting: {
    source: string;
    destination: string;
    factory: FactoryAttribution;
    packs: number;
    bundles: number;
    pieces: number;
    oldest_since: string | null;
  }[];
  warehouse: WarehouseCounts & { by_factory: (WarehouseCounts & { factory: FactoryAttribution })[] };
  materials: (MaterialCounts & { warehouse: string; factory: FactoryAttribution })[];
  material_totals: MaterialCounts[];
  material_varieties?: { item: string; sku: string; unit: string; quantity: string; active_batches: number }[];
};

export type CeoReport = DateRange & {
  grouping: Grouping;
  factory: Factory;
  timezone: string;
  updated_at: string;
  activity: { buckets: ActivityBucket[] };
  balances: BalanceBucket[];
};

export function presetRange(preset: Exclude<Preset, "custom">, today: string): DateRange {
  if (preset === "thisMonth") return { start: `${today.slice(0, 7)}-01`, end: today };
  if (preset === "today") return { start: today, end: today };
  const date = new Date(`${today}T12:00:00Z`);
  const offset = preset === "yesterday" ? 1 : (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - offset);
  const start = date.toISOString().slice(0, 10);
  return { start, end: preset === "yesterday" ? start : today };
}

export function stageTotals(output: Output[]) {
  const totals: Record<Stage, number> = { cutting: 0, printing: 0, sewing: 0, packaging: 0 };
  for (const row of output) totals[row.stage] += row.pieces;
  return totals;
}

export function countTotals(buckets: ActivityBucket[], key: keyof Pick<ActivityBucket,
  "finished_receipts" | "shipments" | "receipts_unassigned" | "shipments_unassigned" | "legacy_imports">): PieceCounts {
  return buckets.reduce((total, bucket) => ({
    packs: total.packs + bucket[key].packs,
    pieces: total.pieces + bucket[key].pieces,
  }), { packs: 0, pieces: 0 });
}
