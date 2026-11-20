export type PackagePlanItem = { model_id: number; color: string; size: string; quantity: number };
export type BatchAllocationPlan = { production_batch_id: number; quantity: number; label: string; item_breakdown?: PackagePlanItem[] | null };
export type PackagePlan = { items: PackagePlanItem[]; batch_allocations?: BatchAllocationPlan[] };
export type NastilPackageSource = { id: number; label: string; available: number };
export type PackageSourceQuantity = { packed_qty: number; packaged_qty: number; available_to_package: number;
  sewing_output_qty: number; available_input_qty: number; actual_size_verified?: boolean;
  size_balances?: Array<{ size: string; accepted: number | null; packaged_qty: number; legacy_unknown_reserved_qty: number; remaining: number | null }> };
export type PackageSourceBalances = { items: Array<PackageSourceQuantity & { id: number; batch_no: string; batch_index: number; name: string | null }>;
  unbatched_source?: PackageSourceQuantity | null };

export const multiNastilText = {
  en: { title: "Pack selected Nastils together", hint: "Choose at least two Nastils ready from Sewing. Create only the packs you need; the remainder stays available and each pack keeps its source quantities.", select: "Select", nastil: "Nastil", available: "Available to pack", selected: "Selected Nastils", chooseTwo: "Choose at least two available Nastils.", remaining: "Pieces left for later", packCount: "Choose a whole number of packs from 1 to 200.", noOutput: "No passed Sewing output is available to pack.", directHint: "Passed Sewing output is ready to pack. Choose a Nastil and pack count; packing and labels are saved together.", sizeHint: "The size mix is suggested from the order. Check the actual contents before creating labels.", create: "Pack and create labels", count: "Packs to create", chooseBatch: "Choose an available Nastil.", planned: "Packages to create", partial: "Allow a partial pack", partialHint: "The last requested pack may contain fewer pieces. All other pieces stay available." },
  ru: { title: "Упаковать выбранные настилы вместе", hint: "Выберите минимум два настила, готовых после пошива. Создайте только нужные упаковки; остаток остаётся доступным, а исходные количества сохраняются.", select: "Выбрать", nastil: "Настил", available: "Доступно для упаковки", selected: "Выбрано настилов", chooseTwo: "Выберите минимум два доступных настила.", remaining: "Остаток на потом", packCount: "Выберите целое число упаковок от 1 до 200.", noOutput: "Нет годного выпуска пошива для упаковки.", directHint: "Годный выпуск пошива готов к упаковке. Выберите настил и число упаковок; упаковка и этикетки сохранятся вместе.", sizeHint: "Состав по размерам предложен из заказа. Перед созданием этикеток проверьте фактическое содержимое.", create: "Упаковать и создать этикетки", count: "Создать упаковок", chooseBatch: "Выберите доступный настил.", planned: "Упаковки к созданию", partial: "Разрешить неполную упаковку", partialHint: "Последняя выбранная упаковка может быть неполной. Остальные изделия останутся доступными." },
  uz: { title: "Tanlangan nastillarni birga qadoqlash", hint: "Tikuvdan tayyor bo‘lgan kamida ikkita nastilni tanlang. Faqat kerakli qadoqlarni yarating; qoldiq mavjud qoladi va har bir qadoqning manba miqdorlari saqlanadi.", select: "Tanlash", nastil: "Nastil", available: "Qadoqlash uchun mavjud", selected: "Tanlangan nastillar", chooseTwo: "Kamida ikkita mavjud nastilni tanlang.", remaining: "Keyin uchun qolgan mahsulot", packCount: "1 dan 200 gacha butun qadoq sonini tanlang.", noOutput: "Qadoqlash uchun tikuvdan o‘tgan mahsulot mavjud emas.", directHint: "Tikuvdan o‘tgan mahsulot qadoqlashga tayyor. Nastil va qadoqlar sonini tanlang; qadoqlash va yorliqlar birga saqlanadi.", sizeHint: "O‘lchamlar tarkibi buyurtmadan taklif qilinadi. Yorliqlarni yaratishdan oldin haqiqiy tarkibni tekshiring.", create: "Qadoqlash va yorliq yaratish", count: "Yaratiladigan qadoqlar", chooseBatch: "Mavjud nastilni tanlang.", planned: "Yaratiladigan qadoqlar", partial: "To‘liq bo‘lmagan qadoqqa ruxsat berish", partialHint: "Oxirgi tanlangan qadoqda kamroq dona bo‘lishi mumkin. Qolgan mahsulot mavjud qoladi." },
};

export const directPackagingDamageText = {
  en: { label: "Damaged pieces (optional)", hint: "Count only newly found damage in this Nastil. Damaged pieces are excluded from labels.", invalid: "Enter a whole damaged quantity within the available Sewing input.", preview: "Preview uses the selected source balance and package contents." },
  ru: { label: "Повреждённые изделия (необязательно)", hint: "Укажите только новый брак в этом настиле. Он не включается в этикетки.", invalid: "Укажите целое количество брака в пределах доступного выпуска пошива.", preview: "Расчёт использует остаток выбранного источника и состав упаковки." },
  uz: { label: "Shikastlangan donalar (ixtiyoriy)", hint: "Faqat shu nastilda yangi aniqlangan nuqsonlarni kiriting. Ular yorliqlarga kiritilmaydi.", invalid: "Mavjud tikuv miqdori doirasida butun nuqsonli dona sonini kiriting.", preview: "Hisob tanlangan manba qoldig‘i va qadoq tarkibidan foydalanadi." },
};

export const packagingDamageActionText = {
  en: { save: "Record damage only", saved: "Damage recorded. No packages or labels were created.", pending: "The previous damage request is unconfirmed. Recover it before recording damage again." },
  ru: { save: "Сохранить только брак", saved: "Брак сохранён. Упаковки и этикетки не создавались.", pending: "Предыдущая запись брака не подтверждена. Восстановите её перед повторной записью." },
  uz: { save: "Faqat nuqsonlarni qayd etish", saved: "Nuqsonlar qayd etildi. Qadoqlar va yorliqlar yaratilmadi.", pending: "Oldingi nuqson so‘rovi tasdiqlanmagan. Qayta kiritishdan oldin uni tiklang." },
};

/** Use only explicitly selected output; never borrow from another Nastil. */
export function planSelectedNastils(items: PackagePlanItem[], sources: NastilPackageSource[], selectedIds: number[], maxPackages = Number.MAX_SAFE_INTEGER) {
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
  for (let index = 0; index < Math.min(maxPackages, Math.floor(totalAvailable / packageTotal)); index += 1) {
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

export type NastilQuantityDraft = Record<number, Record<number, string>>;

export function applyNastilQuantities(plans: PackagePlan[], sources: NastilPackageSource[], draft: NastilQuantityDraft) {
  const used = new Map<number, number>();
  let valid = true;
  const result = plans.map((plan, index) => {
    const expected = plan.items.reduce((total, item) => total + item.quantity, 0);
    const quantities = draft[index];
    const allocations = quantities ? sources.flatMap(source => {
      const quantity = Number(quantities[source.id] ?? 0);
      if (!Number.isInteger(quantity) || quantity < 0 || quantity > source.available) valid = false;
      return quantity > 0 ? [{ production_batch_id: source.id, quantity, label: source.label }] : [];
    }) : plan.batch_allocations ?? [];
    if (allocations.reduce((total, row) => total + row.quantity, 0) !== expected) valid = false;
    for (const row of allocations) used.set(row.production_batch_id, (used.get(row.production_batch_id) ?? 0) + row.quantity);
    return { ...plan, batch_allocations: allocations };
  });
  if (sources.some(source => (used.get(source.id) ?? 0) > source.available)) valid = false;
  return { plans: result, valid };
}

export const nastilQuantityText = {
  en: { adjust: "Adjust quantities by Nastil", invalid: "Each package must match its total and stay within the available Nastil quantities." },
  ru: { adjust: "Изменить количество по настилам", invalid: "Сумма по настилам должна совпадать с количеством в упаковке и не превышать доступный остаток." },
  uz: { adjust: "Nastil bo‘yicha miqdorlarni o‘zgartirish", invalid: "Nastil miqdorlari qadoqdagi jami donaga teng va mavjud qoldiqdan oshmasligi kerak." },
};
