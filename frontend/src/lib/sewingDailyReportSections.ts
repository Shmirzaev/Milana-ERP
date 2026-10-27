const MILANA_SECTIONED_LINE_CODES = new Set([
  "SEW-01",
  "SEW-06",
  "SEW-07",
  "SEW-09",
  "SEW-10",
  "SEW-12",
  "SEW-13",
]);
const SECTIONED_FACTORY_CODES = new Set(["BST", "ECO"]);

export function supportsDynamicSewingReportSections(factoryCode: string, lineCode: string) {
  const factory = factoryCode.trim().toUpperCase();
  const line = lineCode.trim().toUpperCase();
  return SECTIONED_FACTORY_CODES.has(factory) || MILANA_SECTIONED_LINE_CODES.has(line);
}
