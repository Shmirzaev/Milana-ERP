export type PriceCalculationRow = {
  id: string;
  kroyNo: string;
  date: string;
  modelNo: string;
  variantNo: string;
  modelCategory: string;
  modelName: string;
  modelSize: string;
  fabricWidth: string;
  layupMeters: string;
  sizeCount: string;
  gsm: string;
  bindingKgPerPiece: string;
  fabricPrice: string;
  sewingCost: string;
  packagingCost: string;
  accessory1: string;
  accessory2: string;
  accessory3: string;
  accessory4: string;
  costPriceUzs: string;
  sellingPrice: string;
  profitPercentage: string;
  exchangeRate: string;
};

export type EditableField = Exclude<keyof PriceCalculationRow, "id">;

export type CalculatedValues = {
  fabricConsumption: number | null;
  consumptionCost: number | null;
  bindingPrice: number | null;
  costPrice: number | null;
  difference: number | null;
};

export const FIXED_PACKAGING_COST = 0.1;

export type PriceCalculationColumn =
  | {
      kind: "editable";
      field: EditableField;
      labelKey: string;
      inputType: "text" | "date" | "number";
      widthClass: string;
      accessoryNumber?: number;
      readOnly?: boolean;
    }
  | {
      kind: "calculated";
      field: keyof CalculatedValues;
      labelKey: string;
      widthClass: string;
    };

export type PriceCalculationGroup = {
  labelKey: string;
  gridClass: string;
  columns: PriceCalculationColumn[];
};

export const PRICE_CALCULATION_COLUMNS: PriceCalculationColumn[] = [
  { kind: "editable", field: "kroyNo", labelKey: "page.priceCalculation.kroyNo", inputType: "text", widthClass: "w-32" },
  { kind: "editable", field: "date", labelKey: "page.priceCalculation.date", inputType: "date", widthClass: "w-40" },
  { kind: "editable", field: "modelNo", labelKey: "page.priceCalculation.modelNo", inputType: "text", widthClass: "w-36" },
  { kind: "editable", field: "variantNo", labelKey: "page.priceCalculation.variantNo", inputType: "text", widthClass: "w-36" },
  { kind: "editable", field: "modelCategory", labelKey: "page.priceCalculation.modelCategory", inputType: "text", widthClass: "w-44" },
  { kind: "editable", field: "modelName", labelKey: "page.priceCalculation.modelName", inputType: "text", widthClass: "w-44" },
  { kind: "editable", field: "modelSize", labelKey: "page.priceCalculation.modelSize", inputType: "text", widthClass: "w-32" },
  { kind: "editable", field: "fabricWidth", labelKey: "page.priceCalculation.fabricWidth", inputType: "number", widthClass: "w-36" },
  { kind: "editable", field: "layupMeters", labelKey: "page.priceCalculation.layupMeters", inputType: "number", widthClass: "w-32" },
  { kind: "editable", field: "sizeCount", labelKey: "page.priceCalculation.size", inputType: "number", widthClass: "w-28" },
  { kind: "editable", field: "gsm", labelKey: "page.priceCalculation.gsm", inputType: "number", widthClass: "w-28" },
  { kind: "editable", field: "bindingKgPerPiece", labelKey: "page.priceCalculation.bindingKgPerPiece", inputType: "number", widthClass: "w-40" },
  { kind: "calculated", field: "fabricConsumption", labelKey: "page.priceCalculation.fabricConsumption", widthClass: "w-44" },
  { kind: "editable", field: "fabricPrice", labelKey: "page.priceCalculation.fabricPrice", inputType: "number", widthClass: "w-36" },
  { kind: "calculated", field: "consumptionCost", labelKey: "page.priceCalculation.consumptionCost", widthClass: "w-44" },
  { kind: "calculated", field: "bindingPrice", labelKey: "page.priceCalculation.bindingPrice", widthClass: "w-36" },
  { kind: "editable", field: "sewingCost", labelKey: "page.priceCalculation.sewingCost", inputType: "number", widthClass: "w-36" },
  { kind: "editable", field: "packagingCost", labelKey: "page.priceCalculation.packagingCost", inputType: "number", widthClass: "w-40", readOnly: true },
  { kind: "editable", field: "accessory1", labelKey: "page.priceCalculation.accessories", inputType: "number", widthClass: "w-36", accessoryNumber: 1 },
  { kind: "editable", field: "accessory2", labelKey: "page.priceCalculation.accessories", inputType: "number", widthClass: "w-36", accessoryNumber: 2 },
  { kind: "editable", field: "accessory3", labelKey: "page.priceCalculation.accessories", inputType: "number", widthClass: "w-36", accessoryNumber: 3 },
  { kind: "editable", field: "accessory4", labelKey: "page.priceCalculation.accessories", inputType: "number", widthClass: "w-36", accessoryNumber: 4 },
  { kind: "calculated", field: "costPrice", labelKey: "page.priceCalculation.costPrice", widthClass: "w-36" },
  { kind: "editable", field: "costPriceUzs", labelKey: "page.priceCalculation.costPriceUzs", inputType: "number", widthClass: "w-40" },
  { kind: "editable", field: "sellingPrice", labelKey: "page.priceCalculation.sellingPrice", inputType: "number", widthClass: "w-36" },
  { kind: "calculated", field: "difference", labelKey: "page.priceCalculation.difference", widthClass: "w-36" },
  { kind: "editable", field: "profitPercentage", labelKey: "page.priceCalculation.profitPercentage", inputType: "number", widthClass: "w-40" },
  { kind: "editable", field: "exchangeRate", labelKey: "page.priceCalculation.exchangeRate", inputType: "number", widthClass: "w-44" },
];

export const PRICE_CALCULATION_GROUPS: PriceCalculationGroup[] = [
  {
    labelKey: "page.priceCalculation.group.model",
    gridClass: "grid-cols-2 md:grid-cols-4 xl:grid-cols-7",
    columns: PRICE_CALCULATION_COLUMNS.slice(0, 7),
  },
  {
    labelKey: "page.priceCalculation.group.fabric",
    gridClass: "grid-cols-2 md:grid-cols-3 lg:grid-cols-5 xl:grid-cols-9",
    columns: PRICE_CALCULATION_COLUMNS.slice(7, 16),
  },
  {
    labelKey: "page.priceCalculation.group.productionCosts",
    gridClass: "grid-cols-2 md:grid-cols-3 xl:grid-cols-6",
    columns: PRICE_CALCULATION_COLUMNS.slice(16, 22),
  },
  {
    labelKey: "page.priceCalculation.group.finalPricing",
    gridClass: "grid-cols-2 md:grid-cols-3 xl:grid-cols-6",
    columns: PRICE_CALCULATION_COLUMNS.slice(22, 28),
  },
];

const SUMMARY_FIELD_NAMES = new Set<PriceCalculationColumn["field"]>([
  "kroyNo",
  "modelNo",
  "variantNo",
  "modelName",
  "costPrice",
  "sellingPrice",
]);

export const PRICE_CALCULATION_SUMMARY_COLUMNS = PRICE_CALCULATION_COLUMNS.filter(
  (column) => SUMMARY_FIELD_NAMES.has(column.field),
);

export const PRICE_CALCULATION_DETAIL_GROUPS: PriceCalculationGroup[] = PRICE_CALCULATION_GROUPS.map((group) => ({
  ...group,
  gridClass: group.labelKey === "page.priceCalculation.group.model"
    ? "grid-cols-2 md:grid-cols-3"
    : group.labelKey === "page.priceCalculation.group.finalPricing"
      ? "grid-cols-2 md:grid-cols-4"
      : group.gridClass,
  columns: group.columns.filter((column) => !SUMMARY_FIELD_NAMES.has(column.field)),
}));

export function createEmptyPriceCalculationRow(id: string): PriceCalculationRow {
  return {
    id,
    kroyNo: "",
    date: "",
    modelNo: "",
    variantNo: "",
    modelCategory: "",
    modelName: "",
    modelSize: "",
    fabricWidth: "",
    layupMeters: "",
    sizeCount: "",
    gsm: "",
    bindingKgPerPiece: "",
    fabricPrice: "",
    sewingCost: "",
    packagingCost: String(FIXED_PACKAGING_COST),
    accessory1: "",
    accessory2: "",
    accessory3: "",
    accessory4: "",
    costPriceUzs: "",
    sellingPrice: "",
    profitPercentage: "",
    exchangeRate: "",
  };
}

function numeric(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function calculatePriceRow(row: PriceCalculationRow): CalculatedValues {
  const hasConsumptionInputs = Boolean(row.fabricWidth || row.layupMeters || row.gsm || row.sizeCount);
  const sizeCount = numeric(row.sizeCount);
  const fabricConsumption = hasConsumptionInputs && sizeCount > 0
    ? (numeric(row.fabricWidth) * numeric(row.layupMeters) * numeric(row.gsm)) / sizeCount
    : null;
  const consumptionCost = fabricConsumption === null || !row.fabricPrice
    ? null
    : fabricConsumption * numeric(row.fabricPrice);
  const bindingPrice = row.bindingKgPerPiece && row.fabricPrice
    ? numeric(row.bindingKgPerPiece) * numeric(row.fabricPrice)
    : null;
  const costPrice = (consumptionCost ?? 0)
    + (bindingPrice ?? 0)
    + numeric(row.sewingCost)
    + FIXED_PACKAGING_COST
    + numeric(row.accessory1)
    + numeric(row.accessory2)
    + numeric(row.accessory3)
    + numeric(row.accessory4);
  const difference = costPrice !== null && row.sellingPrice
    ? numeric(row.sellingPrice) - costPrice
    : null;

  return { fabricConsumption, consumptionCost, bindingPrice, costPrice, difference };
}
