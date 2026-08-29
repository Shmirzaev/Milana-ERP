import type { NumberInputValue } from "@/lib/numberInput";

export type SectionCode = "sewing" | "pressing" | "packaging";
export type PaidOperationFactory = "milana" | "besttex" | "eco_cotton";

export type QuantityMode = "batch" | "custom";
export type SplitMode = "none" | "equal" | "custom";

export type PaidOperation = {
  id: string;
  selected: boolean;
  section: SectionCode;
  code: string;
  name: string;
  rate: string;
  sewingFactory?: PaidOperationFactory;
  legacySourceId?: string;
  sourceOrder?: number;
  duration?: string;
  currency?: string;
  sourceStage?: string;
  changeDirection?: string;
  finalOperation?: boolean;
  quantityMode: QuantityMode;
  customQuantity: NumberInputValue;
  copies: NumberInputValue;
  splitMode: SplitMode;
  splitQuantities: NumberInputValue[];
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
export const PAID_OPERATION_FACTORIES: PaidOperationFactory[] = ["milana", "besttex", "eco_cotton"];

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

function optionalNumber(value: unknown): number | undefined {
  if (value === "" || value === null || value === undefined) return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

function optionalString(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined;
  return String(value);
}

function optionalBoolean(value: unknown): boolean | undefined {
  if (value === null || value === undefined || value === "") return undefined;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const normalized = String(value).trim().toLowerCase();
  if (["true", "1", "yes"].includes(normalized)) return true;
  if (["false", "0", "no"].includes(normalized)) return false;
  return undefined;
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

export function createPaidOperation(
  prefix = "op",
  customQuantity = 0,
  sewingFactory?: PaidOperationFactory,
): PaidOperation {
  return {
    id: cleanId(prefix),
    selected: true,
    section: "sewing",
    code: "SEW-NEW",
    name: "New operation",
    rate: "",
    ...(sewingFactory ? { sewingFactory } : {}),
    quantityMode: "batch",
    customQuantity,
    copies: 1,
    splitMode: "none",
    splitQuantities: [],
  };
}

export function normalizePaidOperationFactory(value: unknown): PaidOperationFactory | undefined {
  const normalized = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (["mil", "milana", "sml"].includes(normalized)) return "milana";
  if (["bst", "besttex", "btx"].includes(normalized)) return "besttex";
  if (["eco", "eco_cotton", "ecocotton"].includes(normalized)) return "eco_cotton";
  return undefined;
}

export function paidOperationFactoryFromDepartmentCode(value: unknown): PaidOperationFactory | undefined {
  return normalizePaidOperationFactory(value);
}

export function isLegacySharedPaidOperation(operation: PaidOperation): boolean {
  return !normalizePaidOperationFactory(operation.sewingFactory);
}

export function paidOperationMatchesFactory(
  operation: PaidOperation,
  sewingFactory: PaidOperationFactory,
): boolean {
  const configuredFactory = normalizePaidOperationFactory(operation.sewingFactory);
  return !configuredFactory || configuredFactory === sewingFactory;
}

export function materializeLegacyPaidOperations(
  rows: PaidOperation[],
  factories: PaidOperationFactory[] = PAID_OPERATION_FACTORIES,
): PaidOperation[] {
  const configuredRows = rows.filter((row) => !isLegacySharedPaidOperation(row));
  const existingIds = new Set(rows.map((row) => row.id));
  const configuredLegacyKeys = new Set(
    configuredRows
      .filter((row) => row.legacySourceId && row.sewingFactory)
      .map((row) => `${row.legacySourceId}::${row.sewingFactory}`),
  );
  const expanded: PaidOperation[] = [...configuredRows];

  for (const row of rows.filter(isLegacySharedPaidOperation)) {
    for (const factory of factories) {
      if (configuredLegacyKeys.has(`${row.id}::${factory}`)) continue;
      const idBase = `${row.id}--${factory}`;
      let id = idBase;
      let suffix = 2;
      while (existingIds.has(id)) {
        id = `${idBase}-${suffix}`;
        suffix += 1;
      }
      existingIds.add(id);
      expanded.push({
        ...row,
        id,
        sewingFactory: factory,
        legacySourceId: row.id,
        splitQuantities: [...(row.splitQuantities || [])],
      });
    }
  }
  return expanded;
}

export function normalizePaidOperation(row: any, index = 0): PaidOperation {
  const fallback = DEFAULT_PAID_OPERATIONS[index] || DEFAULT_PAID_OPERATIONS[0];
  const sourceOrder = optionalNumber(row?.sourceOrder ?? row?.source_order ?? row?.sequence);
  const duration = optionalString(row?.duration ?? row?.operation_duration);
  const currency = optionalString(row?.currency);
  const sourceStage = optionalString(
    row?.sourceStage
      ?? row?.source_stage
      ?? row?.originalStage
      ?? row?.original_stage
      ?? row?.stage,
  );
  const changeDirection = optionalString(
    row?.changeDirection
      ?? row?.change_direction
      ?? row?.controlChangeDirection
      ?? row?.control_change_direction,
  );
  const finalOperation = optionalBoolean(
    row?.finalOperation
      ?? row?.final_operation
      ?? row?.final,
  );
  const sewingFactory = normalizePaidOperationFactory(
    row?.sewingFactory ?? row?.sewing_factory ?? row?.factory ?? row?.company,
  );
  const legacySourceId = optionalString(row?.legacySourceId ?? row?.legacy_source_id)?.trim();
  return {
    id: String(row?.id || fallback?.id || cleanId("op")),
    selected: row?.selected !== false,
    section: normalizeSection(row?.section || fallback?.section),
    code: String(row?.code || fallback?.code || "").toUpperCase(),
    name: String(row?.name || row?.operation_name || fallback?.name || ""),
    rate: row?.rate === null || row?.rate === undefined ? String(fallback?.rate || "") : String(row.rate),
    ...(sewingFactory ? { sewingFactory } : {}),
    ...(legacySourceId ? { legacySourceId } : {}),
    ...(sourceOrder === undefined ? {} : { sourceOrder }),
    ...(duration === undefined ? {} : { duration }),
    ...(currency === undefined ? {} : { currency }),
    ...(sourceStage === undefined ? {} : { sourceStage }),
    ...(changeDirection === undefined ? {} : { changeDirection }),
    ...(finalOperation === undefined ? {} : { finalOperation }),
    quantityMode: normalizeQuantityMode(row?.quantityMode || row?.quantity_mode || fallback?.quantityMode),
    customQuantity: numberOrZero(row?.customQuantity ?? row?.custom_quantity ?? fallback?.customQuantity),
    copies: Math.max(1, Math.floor(numberOrZero(row?.copies ?? fallback?.copies) || 1)),
    splitMode: normalizeSplitMode(row?.splitMode || row?.split_mode || fallback?.splitMode),
    splitQuantities: normalizeSplitQuantities(row?.splitQuantities ?? row?.split_quantities ?? fallback?.splitQuantities),
  };
}

export function normalizePaidOperations(value: unknown): PaidOperation[] {
  if (!Array.isArray(value)) return clonePaidOperations();
  if (value.length === 0) return [];
  const rows = value.map((row, index) => normalizePaidOperation(row, index));
  return rows;
}

export function paidOperationsFromDetails(details: any): PaidOperation[] {
  if (details && Object.prototype.hasOwnProperty.call(details, "paid_operations")) {
    return normalizePaidOperations(details.paid_operations);
  }
  if (details && Object.prototype.hasOwnProperty.call(details, "paidOperations")) {
    return normalizePaidOperations(details.paidOperations);
  }
  return clonePaidOperations();
}

export function serializePaidOperations(rows: PaidOperation[]): PaidOperation[] {
  return normalizePaidOperations(rows).map((row) => {
    const sourceOrder = optionalNumber(row.sourceOrder);
    const duration = optionalString(row.duration)?.trim();
    const currency = optionalString(row.currency)?.trim();
    const sourceStage = optionalString(row.sourceStage)?.trim();
    const changeDirection = optionalString(row.changeDirection)?.trim();
    const finalOperation = optionalBoolean(row.finalOperation);
    return {
      id: row.id,
      selected: row.selected,
      section: row.section,
      code: row.code.trim().toUpperCase(),
      name: row.name.trim(),
      rate: String(row.rate ?? "").trim(),
      ...(row.sewingFactory ? { sewingFactory: row.sewingFactory } : {}),
      ...(row.legacySourceId ? { legacySourceId: row.legacySourceId } : {}),
      ...(sourceOrder === undefined ? {} : { sourceOrder }),
      ...(duration ? { duration } : {}),
      ...(currency ? { currency } : {}),
      ...(sourceStage ? { sourceStage } : {}),
      ...(changeDirection ? { changeDirection } : {}),
      ...(finalOperation === undefined ? {} : { finalOperation }),
      quantityMode: row.quantityMode,
      customQuantity: numberOrZero(row.customQuantity),
      copies: Math.max(1, Math.floor(numberOrZero(row.copies) || 1)),
      splitMode: row.splitMode,
      splitQuantities: normalizeSplitQuantities(row.splitQuantities),
    };
  });
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
