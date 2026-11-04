export const packageIdentityText = {
  en: { factory: "Sewing factory", all: "All sewing factories", unknown: "Unknown", model: "Model number", variant: "Variant number" },
  ru: { factory: "Швейная фабрика", all: "Все швейные фабрики", unknown: "Неизвестно", model: "Номер модели", variant: "Номер варианта" },
  uz: { factory: "Tikuv fabrikasi", all: "Barcha tikuv fabrikalari", unknown: "Noma’lum", model: "Model raqami", variant: "Variant raqami" },
};

export type SewingOrigin = { sewing_factory_code?: string | null; sewing_factory_codes?: string[] };
export const sewingFactories = { MIL: "Milana", BST: "Besttex", ECO: "Eco Cotton" };

export function sewingFactoryLabel(origin: SewingOrigin, unknown: string) {
  const codes = origin.sewing_factory_codes || (origin.sewing_factory_code ? [origin.sewing_factory_code] : []);
  return codes.map(code => sewingFactories[code as keyof typeof sewingFactories] || unknown).join(", ") || unknown;
}
