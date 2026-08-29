import type { Me } from "@/lib/auth";

export type PriceRequestStatus = "new" | "in_progress" | "complete";

export type PriceRequestAccessory = {
  name: string | null;
  price: number | null;
};

export type PriceCalculationRequest = {
  id: number;
  model_id: number;
  model_no: string;
  variant_no: string;
  model_name: string;
  model_category: string | null;
  model_sizes: string[];
  model_image_url: string | null;
  variant_image_url: string | null;
  kroy_no: string | null;
  cutting_passport_id: number | null;
  date: string | null;
  fabric_width_m: number | null;
  lay_length_m: number | null;
  size_count: number | null;
  gramage: number | null;
  binding_kg_per_piece: number | null;
  fabric_price: number | null;
  sewing_cost: number | null;
  packaging_cost: number;
  accessories: PriceRequestAccessory[];
  cost_price_uzs: number | null;
  selling_price: number | null;
  profit_percentage: number | null;
  exchange_rate: number | null;
  fabric_consumption: number | null;
  consumption_cost: number | null;
  binding_price: number | null;
  cost_price: number | null;
  difference: number | null;
  cutting_status: PriceRequestStatus;
  purchasing_status: PriceRequestStatus;
  accessories_status: PriceRequestStatus;
  overall_status: PriceRequestStatus;
  created_at: string;
  updated_at: string;
};

export function priceRequestSurface(status: PriceRequestStatus): string {
  if (status === "complete") return "border-[#b9d8bd] bg-[#eef8ef]";
  if (status === "in_progress") return "border-[#e4d28f] bg-[#fff8dd]";
  return "border-[#ecc3bf] bg-[#fff1f0]";
}

function normalized(value: unknown): string {
  return String(value ?? "").trim().toLocaleLowerCase();
}

export function isAbbosbekPricingUser(me: Me | undefined): boolean {
  if (!me) return false;
  if (me.permissions.includes("*")) return true;
  const name = normalized(me.name);
  const emailLocal = normalized(me.email).split("@", 1)[0];
  return name === "abbosbek"
    || name.startsWith("abbosbek ")
    || emailLocal === "abbosbek"
    || me.permissions.includes("price_calculation.purchasing");
}

export function isAccessoryPricingUser(me: Me | undefined): boolean {
  if (!me) return false;
  return me.permissions.includes("*")
    || me.permissions.includes("price_calculation.accessories")
    || (normalized(me.department_code) === "str" && me.permissions.includes("storage.items"));
}

export function numberInputValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}
