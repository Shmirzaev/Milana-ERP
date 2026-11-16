import type { BatchAllocationPlan, PackagePlan, PackagePlanItem } from "./multiNastilPackaging";

export type BatchTraceDraft = Record<string, string>;
export type SourceSizeBudgets = Record<number, Record<string, number>>;
export type SavedBatchAllocation = {
  production_batch_id: number;
  quantity: number;
  batch_no?: string | null;
  batch_label?: string | null;
  batch_name?: string | null;
  item_breakdown?: PackagePlanItem[] | null;
};

export const packageBatchTraceText = {
  en: { title: "Contents by Nastil and size", hint: "Enter the actual contents from each Nastil. Every row must match its Nastil quantity, and each size column must match this package.", batch: "Nastil", total: "Total", expected: "Required", pack: "Package", invalid: "Check the quantities by Nastil and size. Row and size totals must match the package.", unknown: "The size breakdown by Nastil was not recorded for this older package.", missing: "Nastil name unavailable", complete: "The quantities by Nastil and size match this package.", actualUnknown: "Sewing sizes are not recorded. Enter the actual contents.", available: "Maximum by size" },
  ru: { title: "Состав по настилам и размерам", hint: "Введите фактический состав из каждого настила. Сумма строки должна совпадать с количеством настила, а сумма столбца размера — с составом упаковки.", batch: "Настил", total: "Итого", expected: "Требуется", pack: "Упаковка", invalid: "Проверьте количества по настилам и размерам. Суммы строк и размеров должны совпадать с упаковкой.", unknown: "Для этой старой упаковки состав по размерам и настилам не записан.", missing: "Название настила недоступно", complete: "Количества по настилам и размерам совпадают с упаковкой.", actualUnknown: "Размеры выпуска пошива не записаны. Введите фактический состав.", available: "Предел по размерам" },
  uz: { title: "Nastil va o‘lcham bo‘yicha tarkib", hint: "Har bir nastildan olingan haqiqiy tarkibni kiriting. Har bir qator yig‘indisi nastil miqdoriga, o‘lcham ustuni yig‘indisi esa qadoq tarkibiga teng bo‘lishi kerak.", batch: "Nastil", total: "Jami", expected: "Kerak", pack: "Qadoq", invalid: "Nastil va o‘lcham miqdorlarini tekshiring. Qator va o‘lcham yig‘indilari qadoqqa mos bo‘lishi kerak.", unknown: "Bu eski qadoq uchun nastil va o‘lcham bo‘yicha tarkib qayd etilmagan.", missing: "Nastil nomi mavjud emas", complete: "Nastil va o‘lcham miqdorlari qadoqqa mos.", actualUnknown: "Tikuv o‘lchamlari qayd etilmagan. Haqiqiy tarkibni kiriting.", available: "O‘lcham bo‘yicha yuqori chegara" },
};

export const flexibleBatchTraceText = {
  en: { hint: "Enter actual contents from the selected Nastils. Size totals must match each package. A Nastil’s use across all packages cannot exceed its available quantity.", limit: "This pack / source available", invalid: "Check package size totals and the total use of each Nastil across all requested packs." },
  ru: { hint: "Введите фактический состав из выбранных настилов. Суммы размеров должны совпадать с каждой упаковкой. Общий расход настила во всех упаковках не может превышать доступное количество.", limit: "В упаковке / доступно в настиле", invalid: "Проверьте суммы размеров упаковок и общий расход каждого настила во всех выбранных упаковках." },
  uz: { hint: "Tanlangan nastillardan haqiqiy tarkibni kiriting. O‘lcham yig‘indilari har bir qadoqqa mos bo‘lishi kerak. Barcha qadoqlarda nastildan ishlatilgan jami miqdor mavjud qoldiqdan oshmasligi kerak.", limit: "Qadoqda / nastilda mavjud", invalid: "Qadoqlarning o‘lcham yig‘indilari va barcha tanlangan qadoqlarda har bir nastildan ishlatilgan jami miqdorni tekshiring." },
};

export const originalBatchTraceText = {
  en: { title: "Originally packed contents by Nastil and size", hint: "Recorded at packing. Remaining warehouse quantities may differ after dispatch." },
  ru: { title: "Первоначально упакованный состав по настилам и размерам", hint: "Зафиксировано при упаковке. Остаток на складе после отгрузки может отличаться." },
  uz: { title: "Dastlab qadoqlangan nastil va o‘lcham tarkibi", hint: "Qadoqlash paytida qayd etilgan. Jo‘natilgandan keyin ombor qoldig‘i farq qilishi mumkin." },
};

export function traceItemKey(item: PackagePlanItem) {
  return JSON.stringify([item.model_id, item.color.trim().toLowerCase(), item.size.trim()]);
}

export function allocationBatchLabel(row: SavedBatchAllocation, fallback: string) {
  return row.batch_label || (row.batch_no ? `${row.batch_no}${row.batch_name ? ` - ${row.batch_name}` : ""}` : row.batch_name) || fallback;
}

export function traceItems(items: PackagePlanItem[]) {
  const rows = new Map<string, PackagePlanItem>();
  for (const item of items) {
    const key = traceItemKey(item);
    const previous = rows.get(key);
    rows.set(key, { ...item, quantity: (previous?.quantity ?? 0) + item.quantity });
  }
  return [...rows.values()];
}

export function traceCellKey(packageIndex: number, batchId: number, item: PackagePlanItem) {
  return JSON.stringify([packageIndex, batchId, traceItemKey(item)]);
}

// A draft belongs to exact contents and sources. Changing either must not move
// entered evidence onto a different package, size or Nastil.
export function packageTracePlanKey(plans: PackagePlan[]) {
  return JSON.stringify(plans.map(plan => [traceItems(plan.items),
    plan.batch_allocations?.map(row => [row.production_batch_id, row.quantity]) ?? []]));
}

export function traceDraftFromSaved(plans: PackagePlan[]): BatchTraceDraft {
  const draft: BatchTraceDraft = {};
  plans.forEach((plan, index) => plan.batch_allocations?.forEach(allocation => {
    for (const item of allocation.item_breakdown ?? []) {
      const key = traceCellKey(index, allocation.production_batch_id, item);
      draft[key] = String(Number(draft[key] ?? 0) + item.quantity);
    }
  }));
  return draft;
}

/** Only a unique identity can be inferred. Ambiguous cells require operator input. */
export function tracePackagePlans(plans: PackagePlan[], draft: BatchTraceDraft, sourceBudgets?: Record<number, number>, sourceSizeBudgets?: SourceSizeBudgets) {
  let valid = true;
  const usedSources = new Map<number, number>();
  const usedSizes = new Map<number, Map<string, number>>();
  const traced = plans.map((plan, index) => {
    const items = traceItems(plan.items);
    const totals = new Map<string, number>();
    const allocations = plan.batch_allocations ?? [];
    if (!allocations.length) return plan;
    const seen = new Set<number>();
    const batch_allocations = allocations.map((allocation): BatchAllocationPlan => {
      if (seen.has(allocation.production_batch_id)) valid = false;
      seen.add(allocation.production_batch_id);
      const item_breakdown: PackagePlanItem[] = [];
      let rowTotal = 0;
      for (const item of items) {
        const raw = draft[traceCellKey(index, allocation.production_batch_id, item)] ?? "";
        const quantity = sourceBudgets ? Number(raw) : allocations.length === 1 ? item.quantity : items.length === 1 ? allocation.quantity : Number(raw);
        if (!Number.isInteger(quantity) || quantity < 0 || quantity > Math.min(item.quantity, allocation.quantity)) valid = false;
        if (quantity > 0 && Number.isInteger(quantity)) item_breakdown.push({ ...item, quantity });
        rowTotal += quantity;
        const sourceSizes = usedSizes.get(allocation.production_batch_id) ?? new Map<string, number>();
        sourceSizes.set(item.size.trim(), (sourceSizes.get(item.size.trim()) ?? 0) + quantity);
        usedSizes.set(allocation.production_batch_id, sourceSizes);
        totals.set(traceItemKey(item), (totals.get(traceItemKey(item)) ?? 0) + quantity);
      }
      if (!Number.isInteger(allocation.quantity) || allocation.quantity <= 0
        || (!sourceBudgets && rowTotal !== allocation.quantity)) valid = false;
      usedSources.set(allocation.production_batch_id, (usedSources.get(allocation.production_batch_id) ?? 0) + rowTotal);
      return { ...allocation, quantity: sourceBudgets ? rowTotal : allocation.quantity, item_breakdown };
    }).filter(row => !sourceBudgets || row.quantity > 0);
    for (const item of items) {
      if (!Number.isInteger(item.quantity) || item.quantity <= 0 || totals.get(traceItemKey(item)) !== item.quantity) valid = false;
    }
    return { ...plan, batch_allocations };
  });
  if (sourceBudgets) for (const [batch, used] of usedSources) {
    const available = sourceBudgets[batch];
    if (!Number.isInteger(used) || used < 0 || available === undefined || !Number.isInteger(available) || used > available) valid = false;
  }
  if (sourceSizeBudgets) for (const [batch, used] of usedSizes) {
    if (!Object.hasOwn(sourceSizeBudgets, batch)) continue;
    for (const [size, quantity] of used) {
      const available = sourceSizeBudgets[batch]?.[size] ?? 0;
      if (!Number.isInteger(available) || quantity > available) valid = false;
    }
  }
  return { plans: traced, valid };
}
