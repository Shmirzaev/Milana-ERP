export const MATERIAL_COLOR_OPTIONS = [
  { value: "Black", labelKey: "materialColor.black" },
  { value: "White", labelKey: "materialColor.white" },
  { value: "Gray", labelKey: "materialColor.gray" },
  { value: "Light Gray", labelKey: "materialColor.lightGray" },
  { value: "Navy", labelKey: "materialColor.navy" },
  { value: "Dark Blue", labelKey: "materialColor.darkBlue" },
  { value: "Blue", labelKey: "materialColor.blue" },
  { value: "Sky Blue", labelKey: "materialColor.skyBlue" },
  { value: "Red", labelKey: "materialColor.red" },
  { value: "Burgundy", labelKey: "materialColor.burgundy" },
  { value: "Pink", labelKey: "materialColor.pink" },
  { value: "Purple", labelKey: "materialColor.purple" },
  { value: "Green", labelKey: "materialColor.green" },
  { value: "Olive", labelKey: "materialColor.olive" },
  { value: "Yellow", labelKey: "materialColor.yellow" },
  { value: "Orange", labelKey: "materialColor.orange" },
  { value: "Brown", labelKey: "materialColor.brown" },
  { value: "Beige", labelKey: "materialColor.beige" },
  { value: "Cream", labelKey: "materialColor.cream" },
  { value: "Ivory", labelKey: "materialColor.ivory" },
  { value: "Khaki", labelKey: "materialColor.khaki" },
  { value: "Rotation", labelKey: "materialColor.rotation" },
] as const;

const MATERIAL_COLOR_LABEL_KEYS = new Map(
  MATERIAL_COLOR_OPTIONS.map((option) => [option.value.toLowerCase(), option.labelKey]),
);

export function materialColorLabelKey(value: unknown): string | null {
  const normalized = String(value || "").trim().toLowerCase();
  return normalized ? MATERIAL_COLOR_LABEL_KEYS.get(normalized) || null : null;
}
