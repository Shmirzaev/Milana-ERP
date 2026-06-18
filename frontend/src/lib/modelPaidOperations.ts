export type SectionCode = "sewing" | "pressing" | "packaging";

export type QuantityMode = "batch" | "custom";
export type SplitMode = "none" | "equal" | "custom";

export type PaidOperation = {
  id: string;
  selected: boolean;
  section: SectionCode;
  code: string;
  name: string;
  rate: string;
  quantityMode: QuantityMode;
  customQuantity: number;
  copies: number;
  splitMode: SplitMode;
  splitQuantities: number[];
};

export const SECTION_LABELS: Record<SectionCode, string> = {
  sewing: "Sewing",
  pressing: "Pressing",
  packaging: "Packaging",
};

export const SECTION_BADGES: Record<SectionCode, string> = {
  sewing: "bg-orange-100 text-orange-800",
  pressing: "bg-sky-100 text-sky-800",
  packaging: "bg-emerald-100 text-emerald-800",
};

const VALID_SECTIONS: SectionCode[] = ["sewing", "pressing", "packaging"];
const VALID_QUANTITY_MODES: QuantityMode[] = ["batch", "custom"];
const VALID_SPLIT_MODES: SplitMode[] = ["none", "equal", "custom"];

export const DEFAULT_PAID_OPERATIONS: PaidOperation[] = [
  {
    id: "sew-front",
    selected: true,
    section: "sewing",
    code: "SEW-FRONT",
    name: "Front body sewing",
    rate: "",
    quantityMode: "batch",
    customQuantity: 0,
    copies: 1,
    splitMode: "none",
    splitQuantities: [],
  },
  {
    id: "sew-back",
    selected: true,
    section: "sewing",
    code: "SEW-BACK",
    name: "Back body sewing",
    rate: "",
    quantityMode: "batch",
    customQuantity: 0,
    copies: 1,
    splitMode: "none",
    splitQuantities: [],
  },
  {
    id: "sew-assembly",
    selected: true,
    section: "sewing",
    code: "SEW-ASM",
    name: "Assembly sewing",
    rate: "",
    quantityMode: "batch",
    customQuantity: 0,
    copies: 1,
    splitMode: "none",
    splitQuantities: [],
  },
  {
    id: "pressing",
    selected: true,
    section: "pressing",
    code: "PRS-PRESS",
    name: "Pressing",
    rate: "",
    quantityMode: "batch",
    customQuantity: 0,
    copies: 1,
    splitMode: "none",
    splitQuantities: [],
  },
  {
    id: "packaging",
    selected: true,
    section: "packaging",
    code: "PKG-PACK",
    name: "Packaging",
    rate: "",
    quantityMode: "batch",
    customQuantity: 0,
    copies: 1,
    splitMode: "none",
    splitQuantities: [],
  },
];

function numberOrZero(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function cleanId(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

function normalizeSection(value: unknown): SectionCode {
  const normalized = String(value || "").toLowerCase();
  return VALID_SECTIONS.includes(normalized as SectionCode) ? normalized as SectionCode : "sewing";
}

function normalizeQuantityMode(value: unknown): QuantityMode {
  const normalized = String(value || "").toLowerCase();
  return VALID_QUANTITY_MODES.includes(normalized as QuantityMode) ? normalized as QuantityMode : "batch";
}

function normalizeSplitMode(value: unknown): SplitMode {
  const normalized = String(value || "").toLowerCase();
  return VALID_SPLIT_MODES.includes(normalized as SplitMode) ? normalized as SplitMode : "none";
}

function normalizeSplitQuantities(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value.map(numberOrZero).filter((quantity) => quantity >= 0);
}

export function clonePaidOperations(rows: PaidOperation[] = DEFAULT_PAID_OPERATIONS): PaidOperation[] {
  return rows.map((row) => ({ ...row, splitQuantities: [...(row.splitQuantities || [])] }));
}

export function createPaidOperation(prefix = "op", customQuantity = 0): PaidOperation {
  return {
    id: cleanId(prefix),
    selected: true,
    section: "sewing",
    code: "SEW-NEW",
    name: "New operation",
    rate: "",
    quantityMode: "batch",
    customQuantity,
    copies: 1,
    splitMode: "none",
    splitQuantities: [],
  };
}

export function normalizePaidOperation(row: any, index = 0): PaidOperation {
  const fallback = DEFAULT_PAID_OPERATIONS[index] || DEFAULT_PAID_OPERATIONS[0];
  return {
    id: String(row?.id || fallback?.id || cleanId("op")),
    selected: row?.selected !== false,
    section: normalizeSection(row?.section || fallback?.section),
    code: String(row?.code || fallback?.code || "").toUpperCase(),
    name: String(row?.name || row?.operation_name || fallback?.name || ""),
    rate: row?.rate === null || row?.rate === undefined ? String(fallback?.rate || "") : String(row.rate),
    quantityMode: normalizeQuantityMode(row?.quantityMode || row?.quantity_mode || fallback?.quantityMode),
    customQuantity: numberOrZero(row?.customQuantity ?? row?.custom_quantity ?? fallback?.customQuantity),
    copies: Math.max(1, Math.floor(numberOrZero(row?.copies ?? fallback?.copies) || 1)),
    splitMode: normalizeSplitMode(row?.splitMode || row?.split_mode || fallback?.splitMode),
    splitQuantities: normalizeSplitQuantities(row?.splitQuantities ?? row?.split_quantities ?? fallback?.splitQuantities),
  };
}

export function normalizePaidOperations(value: unknown): PaidOperation[] {
  if (!Array.isArray(value) || value.length === 0) return clonePaidOperations();
  const rows = value.map((row, index) => normalizePaidOperation(row, index));
  return rows.length ? rows : clonePaidOperations();
}

export function paidOperationsFromDetails(details: any): PaidOperation[] {
  return normalizePaidOperations(details?.paid_operations || details?.paidOperations);
}

export function serializePaidOperations(rows: PaidOperation[]): PaidOperation[] {
  return normalizePaidOperations(rows).map((row) => ({
    id: row.id,
    selected: row.selected,
    section: row.section,
    code: row.code.trim().toUpperCase(),
    name: row.name.trim(),
    rate: String(row.rate ?? "").trim(),
    quantityMode: row.quantityMode,
    customQuantity: numberOrZero(row.customQuantity),
    copies: Math.max(1, Math.floor(numberOrZero(row.copies) || 1)),
    splitMode: row.splitMode,
    splitQuantities: normalizeSplitQuantities(row.splitQuantities),
  }));
}

export function withPaidOperations<T extends Record<string, any> | undefined | null>(
  details: T,
  rows: PaidOperation[],
): Record<string, any> {
  return {
    ...(details || {}),
    paid_operations: serializePaidOperations(rows),
  };
}
