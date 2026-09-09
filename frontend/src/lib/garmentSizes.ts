const ADULT_SIZES: readonly string[] = [
  "44",
  "46",
  "48",
  "50",
  "52",
  "54",
  "56",
  "58",
  "60",
  "62",
  "64",
  "66",
  "68",
];

const CHILD_SIZES: readonly string[] = [
  "98", "104", "110", "116", "122", "128", "134",
  "140", "146", "152", "158", "164", "170", "176",
];

export const GARMENT_SIZE_OPTIONS: readonly string[] = [...ADULT_SIZES, ...CHILD_SIZES];

export function garmentSizeRangeEndOptions(from: string): readonly string[] {
  const family = [ADULT_SIZES, CHILD_SIZES].find((sizes) => sizes.includes(from));
  return family ? family.slice(family.indexOf(from)) : [];
}

export function garmentSizeRange(from: string, to: string): readonly string[] {
  // Adult clothing sizes and children's heights are separate size charts.
  const options = garmentSizeRangeEndOptions(from);
  const end = options.indexOf(to);
  return end >= 0 ? options.slice(0, end + 1) : [];
}
