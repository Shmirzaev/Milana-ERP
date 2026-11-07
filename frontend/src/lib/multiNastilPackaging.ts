export type PackagePlanItem = { model_id: number; color: string; size: string; quantity: number };
export type BatchAllocationPlan = { production_batch_id: number; quantity: number; label: string };
export type PackagePlan = { items: PackagePlanItem[]; batch_allocations?: BatchAllocationPlan[] };
export type NastilPackageSource = { id: number; label: string; available: number };
export type PackageSourceBalances = { items: Array<{ id: number; batch_no: string; batch_index: number; name: string | null;
  packed_qty: number; packaged_qty: number; available_to_package: number }> };

export const multiNastilText = {
  en: { title: "Pack selected Nastils together", hint: "Choose at least two Nastils with saved Packaging output. All available output from your selection is included; each pack keeps its source quantities.", select: "Select", nastil: "Nastil", available: "Available to pack", selected: "Selected Nastils", chooseTwo: "Choose at least two available Nastils.", noOutput: "Save Packaging output for each Nastil after Sewing before combining packs." },
  ru: { title: "Упаковать выбранные настилы вместе", hint: "Выберите минимум два настила с сохранённым выпуском упаковки. Весь доступный выпуск выбранных настилов включается в упаковки с сохранением исходных количеств.", select: "Выбрать", nastil: "Настил", available: "Доступно для упаковки", selected: "Выбрано настилов", chooseTwo: "Выберите минимум два доступных настила.", noOutput: "После пошива сохраните выпуск упаковки по каждому настилу, затем объединяйте упаковки." },
  uz: { title: "Tanlangan nastillarni birga qadoqlash", hint: "Qadoqlash natijasi saqlangan kamida ikkita nastilni tanlang. Tanlangan nastillarning barcha mavjud miqdori qadoqlanadi va manba miqdorlari saqlanadi.", select: "Tanlash", nastil: "Nastil", available: "Qadoqlash uchun mavjud", selected: "Tanlangan nastillar", chooseTwo: "Kamida ikkita mavjud nastilni tanlang.", noOutput: "Tikuvdan keyin har bir nastilning qadoqlash natijasini saqlang, so‘ng qadoqlarni birlashtiring." },
};

/** Use only explicitly selected saved output; never borrow from another Nastil. */
export function planSelectedNastils(items: PackagePlanItem[], sources: NastilPackageSource[], selectedIds: number[]) {
  const selected = new Set(selectedIds);
  const seen = new Set<number>();
  const remaining = sources.filter(source => {
    if (!selected.has(source.id) || seen.has(source.id) || !Number.isInteger(source.available) || source.available <= 0) return false;
    seen.add(source.id);
    return true;
  }).map(source => ({ ...source }));
  const totalAvailable = remaining.reduce((sum, source) => sum + source.available, 0);
  const packageTotal = items.reduce((sum, item) => sum + item.quantity, 0);
  const empty = { plans: [] as PackagePlan[], totalAvailable, pendingQty: 0,
    pendingAllocations: [] as BatchAllocationPlan[], crossBatchCount: 0, previewLines: [] as string[] };
  if (remaining.length < 2 || !items.length || !items.every(item => Number.isInteger(item.quantity) && item.quantity > 0)) return empty;
  const plans: PackagePlan[] = [];
  let sourceIndex = 0;
  for (let index = 0; index < Math.floor(totalAvailable / packageTotal); index += 1) {
    let left = packageTotal;
    const allocations: BatchAllocationPlan[] = [];
    while (left > 0 && sourceIndex < remaining.length) {
      const source = remaining[sourceIndex]!;
      const take = Math.min(left, source.available);
      allocations.push({ production_batch_id: source.id, quantity: take, label: source.label });
      source.available -= take;
      left -= take;
      if (!source.available) sourceIndex += 1;
    }
    plans.push({ items, batch_allocations: allocations });
  }
  const pendingAllocations = remaining.slice(sourceIndex).filter(source => source.available > 0).map(source => ({
    production_batch_id: source.id, quantity: source.available, label: source.label,
  }));
  const mixed = plans.filter(plan => plan.batch_allocations!.length > 1);
  return { plans, totalAvailable, pendingQty: pendingAllocations.reduce((sum, source) => sum + source.quantity, 0),
    pendingAllocations, crossBatchCount: mixed.length,
    previewLines: mixed.slice(0, 3).map(plan => plan.batch_allocations!.map(source => `${source.label}: ${source.quantity}`).join(" + ")) };
}
