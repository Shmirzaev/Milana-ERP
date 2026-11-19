import type { Lang } from "@/lib/i18n/types";

export type PassportBatchAllocation = { stock_batch_id: number; quantity: string | number; batch_no?: string };
export type PassportBatchInfo = {
  id: number; batch_no: string; item_id: number; color?: string | null; unit: string;
  width?: number | null; gsm?: number | null; available_quantity?: number | null;
};
export type PassportUsageInputs = {
  layer_weight_kg?: string | number | null; total_layers?: string | number | null;
  scrap_kg?: string | number | null; planned_kg?: string | number | null;
  beka_per_piece_kg?: string | number | null; pieces?: string | number | null; meter_mode?: boolean;
};
type DecimalInput = { coefficient: bigint; scale: number };
function decimalInput(value: unknown): DecimalInput | null {
  const text = value == null || value === "" ? "0" : String(value).trim();
  const match = /^\+?(\d*)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(text);
  if (!match || !(match[1] || match[2]) || !Number.isFinite(Number(text))) return null;
  const scale = (match[2]?.length || 0) - Number(match[3] || 0);
  if (Math.abs(scale) > 50) return null;
  const coefficient = BigInt((match[1] || "0") + (match[2] || ""));
  return scale < 0 ? { coefficient: coefficient * 10n ** BigInt(-scale), scale: 0 } : { coefficient, scale };
}
function addDecimal(a: DecimalInput, b: DecimalInput): DecimalInput {
  const scale = Math.max(a.scale, b.scale);
  return { coefficient: a.coefficient * 10n ** BigInt(scale - a.scale) + b.coefficient * 10n ** BigInt(scale - b.scale), scale };
}
const multiplyDecimal = (a: DecimalInput, b: DecimalInput): DecimalInput => ({ coefficient: a.coefficient * b.coefficient, scale: a.scale + b.scale });
function roundUsage(value: DecimalInput) {
  if (value.scale <= 3) return Number(value.coefficient * 10n ** BigInt(3 - value.scale)) / 1000;
  const divisor = 10n ** BigInt(value.scale - 3), quotient = value.coefficient / divisor, remainder = value.coefficient % divisor;
  // Decimal ROUND_HALF_EVEN is the stock-ledger contract, including exact ties.
  const increment = remainder * 2n > divisor || (remainder * 2n === divisor && quotient % 2n !== 0n);
  return Number(quotient + (increment ? 1n : 0n)) / 1000;
}
export const passportUsageQuantity = (row: PassportUsageInputs) => {
  const layer = decimalInput(row.layer_weight_kg), layers = decimalInput(row.total_layers);
  const scrap = decimalInput(row.scrap_kg), planned = decimalInput(row.planned_kg);
  const binding = decimalInput(row.beka_per_piece_kg), pieces = decimalInput(row.pieces);
  if (!layer || !layers || !scrap || !planned || !binding || !pieces) return NaN;
  // Mirrors the existing stock-ledger formula, including meter-mode binding.
  if (layer.coefficient > 0n && layers.coefficient > 0n) {
    const amount = addDecimal(multiplyDecimal(layer, layers), scrap);
    return roundUsage(row.meter_mode ? addDecimal(amount, multiplyDecimal(binding, pieces)) : amount);
  }
  return roundUsage(planned);
};
export const passportSourceIds = (row: { stock_batch_id: number; batch_allocations?: PassportBatchAllocation[] }) =>
  row.batch_allocations?.length ? row.batch_allocations.map(source => source.stock_batch_id) : [row.stock_batch_id];

export function compatiblePassportBatches(a?: PassportBatchInfo, b?: PassportBatchInfo) {
  if (!a || !b || !a.item_id || a.item_id !== b.item_id) return false;
  const clean = (value?: string | null) => String(value || "").trim().toLowerCase();
  if (clean(a.color) !== clean(b.color) || clean(a.unit) !== clean(b.unit) || !["kg", "m"].includes(clean(a.unit))) return false;
  return (["width", "gsm"] as const).every(key => a[key] == null || b[key] == null || Number(a[key]) === Number(b[key]));
}
export const compatiblePassportGroup = (batches: Array<PassportBatchInfo | undefined>) =>
  batches.every((batch, index) => batches.slice(index).every(other => compatiblePassportBatches(batch, other)));

export type PassportSplitProblem = "amount" | "duplicate" | "mismatch" | "incompatible" | "stock";
export function passportSplitProblem(row: PassportUsageInputs & { stock_batch_id: number; batch_allocations?: PassportBatchAllocation[] }, batches: Record<number, PassportBatchInfo>, checkStock = true): PassportSplitProblem | null {
  const sources = row.batch_allocations || [];
  if (!sources.length) return null;
  const quantities = sources.map(source => source.quantity === "" ? NaN : Number(source.quantity));
  if (quantities.some(q => !Number.isFinite(q) || q <= 0 || q > 9_999_999_999.999 || Math.abs(q * 1000 - Math.round(q * 1000)) > 0.0001)) return "amount";
  if (new Set(sources.map(source => source.stock_batch_id)).size !== sources.length || sources[0]?.stock_batch_id !== row.stock_batch_id) return "duplicate";
  if (sources.some(source => String(batches[source.stock_batch_id]?.unit || "").trim().toLowerCase() !== (row.meter_mode ? "m" : "kg"))) return "incompatible";
  if (!compatiblePassportGroup(sources.map(source => batches[source.stock_batch_id]))) return "incompatible";
  if (checkStock && sources.some(source => {
    const available = batches[source.stock_batch_id]?.available_quantity;
    return available != null && Number(source.quantity) > available;
  })) return "stock";
  const total = quantities.reduce((sum, q) => sum + Math.round(q * 1000), 0);
  if (total !== Math.round(passportUsageQuantity(row) * 1000)) return "mismatch";
  return null;
}

const messages = {
  en: {
    title: "Fabric batches", add: "Add batch to this entry", same: "Same fabric, color, unit and measurements", once: "Enter the cutting information once for all these batches.",
    batch: "Source batch", amount: "Amount to use", available: "Available", total: "Total from batches", expected: "Stock usage to allocate", matched: "Batch split matches stock usage.",
    remove: "Remove batch", separate: "Separate batch", assigned: "Assigned to order", choose: "Select a fabric batch", merge: "Use the cutting details from this entry. The selected batch's separate details will be replaced.",
    locked: "Batch allocations are locked after Cutting confirmation.", empty: "Enter quantities for each batch.",
    amountError: "Enter a positive amount with up to three decimal places for each batch.", duplicateError: "Use each batch only once.",
    mismatchError: "The batch total must equal the stock usage to allocate.", incompatibleError: "Choose batches of the same fabric, color, unit and compatible width/GSM.", stockError: "A batch amount exceeds its available stock.",
  },
  ru: {
    title: "Партии ткани", add: "Добавить партию к этой записи", same: "Одинаковые ткань, цвет, единица и параметры", once: "Введите данные раскроя один раз для всех этих партий.",
    batch: "Партия-источник", amount: "Расход", available: "Доступно", total: "Всего из партий", expected: "Расход для распределения", matched: "Распределение совпадает с расходом.",
    remove: "Убрать партию", separate: "Отделить партию", assigned: "Назначена заказу", choose: "Выберите партию ткани", merge: "Используются данные раскроя этой записи. Отдельные данные выбранной партии будут заменены.",
    locked: "Распределение партий заблокировано после подтверждения раскроя.", empty: "Введите расход для каждой партии.",
    amountError: "Для каждой партии укажите положительный расход с точностью до трёх знаков.", duplicateError: "Используйте каждую партию только один раз.",
    mismatchError: "Сумма по партиям должна совпадать с расходом для распределения.", incompatibleError: "Выберите партии одной ткани, цвета, единицы и совместимых ширины/плотности.", stockError: "Расход партии превышает доступный остаток.",
  },
  uz: {
    title: "Mato partiyalari", add: "Shu yozuvga partiya qo‘shish", same: "Bir xil mato, rang, birlik va o‘lchovlar", once: "Ushbu partiyalar uchun bichish ma’lumotlarini bir marta kiriting.",
    batch: "Manba partiya", amount: "Sarflanadigan miqdor", available: "Mavjud", total: "Partiyalardan jami", expected: "Taqsimlanadigan sarf", matched: "Partiyalar taqsimoti sarfga mos.",
    remove: "Partiyani olib tashlash", separate: "Partiyani ajratish", assigned: "Buyurtmaga biriktirilgan", choose: "Mato partiyasini tanlang", merge: "Shu yozuvdagi bichish ma’lumotlari ishlatiladi. Tanlangan partiyaning alohida ma’lumotlari almashtiriladi.",
    locked: "Bichish tasdiqlangandan keyin partiyalar taqsimoti qulflanadi.", empty: "Har bir partiya uchun miqdorni kiriting.",
    amountError: "Har bir partiya uchun musbat miqdorni ko‘pi bilan uchta kasr xonasi bilan kiriting.", duplicateError: "Har bir partiyani faqat bir marta ishlating.",
    mismatchError: "Partiyalar jami taqsimlanadigan sarfga teng bo‘lishi kerak.", incompatibleError: "Matosi, rangi, birligi va eni/grammaji mos partiyalarni tanlang.", stockError: "Partiya sarfi mavjud qoldiqdan oshib ketdi.",
  },
};
export const passportBatchText = (lang: Lang) => messages[lang] || messages.en;
export const passportSplitErrorText = (problem: PassportSplitProblem, lang: Lang) => passportBatchText(lang)[`${problem}Error`];
