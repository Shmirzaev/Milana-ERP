type UnknownRecord = Record<string, unknown>;

export type OldErpGeneralInfo = {
  sourceDate: string;
  sewModelCode: string;
  product: string;
  originalName: string;
  modelVariant: string;
  description: string;
  style: string;
  company: string;
  planningType: string;
  parentSewModel: string;
  embroidery: boolean | string | null;
  thermalPrint: boolean | string | null;
};

export type OldErpRecipeRow = {
  order: string;
  product: string;
  quantity: string;
  sewingTypeList: string;
};

export type OldErpModelInfo = {
  general: OldErpGeneralInfo | null;
  recipes: OldErpRecipeRow[];
};

const GENERAL_SECTION_KEYS = new Set([
  "date",
  "source_date",
  "sourcedate",
  "sew_model_code",
  "sewmodelcode",
  "model_code",
  "modelcode",
  "code",
  "product",
  "name",
  "original_name",
  "originalname",
  "variant",
  "model_variant",
  "modelvariant",
  "variant_no",
  "variantno",
  "description",
  "style",
  "company",
  "planning_type",
  "planningtype",
  "parent_sew_model",
  "parentsewmodel",
  "embroidery",
  "thermal_print",
  "thermalprint",
]);

const RECIPE_SECTION_KEYS = new Set([
  "no",
  "number",
  "order",
  "sequence",
  "product",
  "qty",
  "quantity",
  "sewingtypelist",
  "sewing_type_list",
]);

function asRecord(value: unknown): UnknownRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as UnknownRecord;
}

function normalizedKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function hasRecognizedKey(value: UnknownRecord, keys: Set<string>): boolean {
  return Object.keys(value).some((key) => {
    const lower = key.toLowerCase();
    return keys.has(lower) || keys.has(normalizedKey(lower));
  });
}

function readAlias(source: UnknownRecord, aliases: string[]): unknown {
  for (const alias of aliases) {
    if (Object.prototype.hasOwnProperty.call(source, alias)) return source[alias];
  }
  const byNormalizedKey = new Map(
    Object.entries(source).map(([key, value]) => [normalizedKey(key), value]),
  );
  for (const alias of aliases) {
    const normalized = normalizedKey(alias);
    if (byNormalizedKey.has(normalized)) return byNormalizedKey.get(normalized);
  }
  return undefined;
}

function isMeaningful(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.some(isMeaningful);
  return typeof value === "boolean" || typeof value === "number";
}

function firstValue(sources: UnknownRecord[], aliases: string[]): unknown {
  for (const source of sources) {
    const value = readAlias(source, aliases);
    if (isMeaningful(value)) return value;
  }
  return undefined;
}

function textValue(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map(textValue).filter(Boolean).join(", ");
  }
  if (!isMeaningful(value)) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function flagValue(value: unknown): boolean | string | null {
  if (!isMeaningful(value)) return null;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (value === 1) return true;
    if (value === 0) return false;
    return String(value);
  }
  const text = textValue(value);
  const normalized = text.toLowerCase();
  if (["true", "yes", "1", "\u0434\u0430", "ha"].includes(normalized)) return true;
  if (["false", "no", "0", "\u043d\u0435\u0442", "yo'q", "yo\u02bbq"].includes(normalized)) return false;
  return text || null;
}

function generalRecordsFromSection(value: unknown): UnknownRecord[] {
  if (Array.isArray(value)) {
    return value.flatMap((row) => generalRecordsFromSection(row));
  }
  const record = asRecord(value);
  if (!record) return [];

  const scalar = asRecord(record.scalar);
  if (scalar) return [scalar];
  if (hasRecognizedKey(record, GENERAL_SECTION_KEYS)) return [record];

  for (const key of ["records", "rows", "items", "general"]) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      const rows = generalRecordsFromSection(record[key]);
      if (rows.length) return rows;
    }
  }

  return Object.entries(record)
    .sort(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }))
    .flatMap(([, row]) => generalRecordsFromSection(row));
}

function recipeRecordsFromSection(value: unknown): UnknownRecord[] {
  if (Array.isArray(value)) {
    return value.flatMap((row) => recipeRecordsFromSection(row));
  }
  const record = asRecord(value);
  if (!record) return [];
  if (hasRecognizedKey(record, RECIPE_SECTION_KEYS)) return [record];

  for (const key of ["records", "rows", "items", "recipes", "recipe"]) {
    if (Object.prototype.hasOwnProperty.call(record, key)) {
      const rows = recipeRecordsFromSection(record[key]);
      if (rows.length) return rows;
    }
  }

  return Object.entries(record)
    .sort(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }))
    .flatMap(([, row]) => recipeRecordsFromSection(row));
}

function migrationContainers(details: UnknownRecord, migration: UnknownRecord): UnknownRecord[] {
  const completeSectionCandidates = [
    migration.complete_sections,
    migration.completeSections,
    migration.sections,
    details.old_erp_complete_sections,
    details.oldErpCompleteSections,
    details.complete_sections,
    details.completeSections,
  ];
  const completeRecordContainers = [
    migration.complete_record,
    migration.completeRecord,
  ]
    .map(asRecord)
    .filter((row): row is UnknownRecord => row !== null);
  const completeSectionContainers = completeSectionCandidates
    .map(asRecord)
    .filter((row): row is UnknownRecord => row !== null)
    .flatMap((container) => [
      container,
      ...Object.entries(container)
        .sort(([left], [right]) => left.localeCompare(right, undefined, { numeric: true }))
        .map(([, value]) => asRecord(value))
        .filter((row): row is UnknownRecord => row !== null),
    ]);
  return [...completeSectionContainers, ...completeRecordContainers, migration];
}

function completeGeneralRecords(containers: UnknownRecord[]): UnknownRecord[] {
  for (const container of containers) {
    for (const key of ["general", "general_info", "generalInfo", "model_general", "modelGeneral"]) {
      if (!Object.prototype.hasOwnProperty.call(container, key)) continue;
      const records = generalRecordsFromSection(container[key]);
      if (records.length) return records;
    }
  }
  return [];
}

function provenanceDetailRecords(migration: UnknownRecord): UnknownRecord[] {
  const detailsByModel = asRecord(migration.details_and_sizes)
    || asRecord(migration.detailsAndSizes);
  if (!detailsByModel) return [];

  const preferredIds = [
    migration.master_record,
    migration.masterRecord,
    ...(Array.isArray(migration.master_records) ? migration.master_records : []),
    ...(Array.isArray(migration.masterRecords) ? migration.masterRecords : []),
    migration.metadata_only_record,
    migration.metadataOnlyRecord,
    ...(Array.isArray(migration.metadata_only_records) ? migration.metadata_only_records : []),
    ...(Array.isArray(migration.metadataOnlyRecords) ? migration.metadataOnlyRecords : []),
  ]
    .map(asRecord)
    .filter((row): row is UnknownRecord => row !== null)
    .map((row) => textValue(readAlias(row, ["old_model_id", "oldModelId", "id"])))
    .filter(Boolean);

  const keys = [
    ...preferredIds.filter((key) => Object.prototype.hasOwnProperty.call(detailsByModel, key)),
    ...Object.keys(detailsByModel)
      .filter((key) => !preferredIds.includes(key))
      .sort((left, right) => left.localeCompare(right, undefined, { numeric: true })),
  ];

  return keys.flatMap((key) => generalRecordsFromSection(detailsByModel[key]));
}

function masterRecords(migration: UnknownRecord): UnknownRecord[] {
  return [
    migration.master_record,
    migration.masterRecord,
    ...(Array.isArray(migration.master_records) ? migration.master_records : []),
    ...(Array.isArray(migration.masterRecords) ? migration.masterRecords : []),
    migration.metadata_only_record,
    migration.metadataOnlyRecord,
    ...(Array.isArray(migration.metadata_only_records) ? migration.metadata_only_records : []),
    ...(Array.isArray(migration.metadataOnlyRecords) ? migration.metadataOnlyRecords : []),
  ]
    .map(asRecord)
    .filter((row): row is UnknownRecord => row !== null);
}

type MigrationFallback = {
  migration: UnknownRecord;
  containers: UnknownRecord[];
};

function buildGeneralInfo(
  details: UnknownRecord,
  migration: UnknownRecord,
  containers: UnknownRecord[],
  fallbacks: MigrationFallback[] = [],
): OldErpGeneralInfo | null {
  const currentGeneral = asRecord(details.general);
  const sources = [
    ...completeGeneralRecords(containers),
    ...provenanceDetailRecords(migration),
    ...(currentGeneral ? [currentGeneral] : []),
    ...masterRecords(migration),
    ...fallbacks.flatMap((fallback) => [
      ...completeGeneralRecords(fallback.containers),
      ...provenanceDetailRecords(fallback.migration),
      ...masterRecords(fallback.migration),
    ]),
  ];
  if (!sources.length) return null;

  const general: OldErpGeneralInfo = {
    sourceDate: textValue(firstValue(sources, ["source_date", "sourceDate", "date", "legacy_source_date", "legacySourceDate"])),
    sewModelCode: textValue(firstValue(sources, ["sew_model_code", "sewModelCode", "model_code", "modelCode", "code", "legacy_sew_model_code", "legacySewModelCode"])),
    product: textValue(firstValue(sources, ["product", "legacy_product", "legacyProduct"])),
    originalName: textValue(firstValue(sources, ["original_name", "originalName", "name", "sew_model_name", "sewModelName", "legacy_name", "legacyName", "legacy_sew_model_name", "legacySewModelName"])),
    modelVariant: textValue(firstValue(sources, ["variant", "model_variant", "modelVariant", "variant_no", "variantNo", "legacy_model_variant", "legacyModelVariant"])),
    description: textValue(firstValue(sources, ["description", "legacy_description", "legacyDescription"])),
    style: textValue(firstValue(sources, ["style", "legacy_style", "legacyStyle"])),
    company: textValue(firstValue(sources, ["company", "legacy_company", "legacyCompany"])),
    planningType: textValue(firstValue(sources, ["planning_type", "planningType", "legacy_planning_type", "legacyPlanningType"])),
    parentSewModel: textValue(firstValue(sources, ["parent_sew_model", "parentSewModel", "legacy_parent_sew_model", "legacyParentSewModel"])),
    embroidery: flagValue(firstValue(sources, ["embroidery", "legacy_master_embroidery", "legacyMasterEmbroidery", "legacy_embroidery", "legacyEmbroidery"])),
    thermalPrint: flagValue(firstValue(sources, ["thermal_print", "thermalPrint", "legacy_master_thermal_print", "legacyMasterThermalPrint", "legacy_thermal_print", "legacyThermalPrint"])),
  };

  const hasValue = Object.values(general).some((value) => value !== "" && value !== null);
  return hasValue ? general : null;
}

function buildRecipes(containers: UnknownRecord[]): OldErpRecipeRow[] {
  const aliases = [
    "recipes",
    "recipe",
    "sew_model_recipe",
    "sewModelRecipe",
    "model_recipe",
    "modelRecipe",
    "recipe_rows",
    "recipeRows",
    "sew_model_recipes",
    "sewModelRecipes",
    "fabric_accessories",
    "fabricAccessories",
  ];
  let rawRows: UnknownRecord[] = [];
  for (const container of containers) {
    for (const alias of aliases) {
      if (!Object.prototype.hasOwnProperty.call(container, alias)) continue;
      rawRows = recipeRecordsFromSection(container[alias]);
      break;
    }
    if (rawRows.length) break;
  }

  return rawRows
    .map((row, index) => ({
      order: textValue(firstValue([row], ["no", "number", "order", "sequence", "source_order", "sourceOrder", "index", "\u2116"])) || String(index + 1),
      product: textValue(firstValue([row], ["product", "name", "item", "material"])),
      quantity: textValue(firstValue([row], ["qty", "quantity", "amount"])),
      sewingTypeList: textValue(firstValue([row], ["sewingTypeList", "sewing_type_list", "sewingType", "sewing_type", "type"])),
    }))
    .filter((row) => row.product || row.quantity || row.sewingTypeList);
}

export function oldErpModelInfoFromDetails(value: unknown): OldErpModelInfo {
  const details = asRecord(value) || {};
  const correctionMigration = asRecord(details.old_erp_migration)
    || asRecord(details.oldErpMigration);
  const deltaMigration = asRecord(details.old_erp_delta_migration)
    || asRecord(details.oldErpDeltaMigration);
  const migration = correctionMigration || deltaMigration || {};
  const containers = migrationContainers(details, migration);
  const deltaFallback = correctionMigration && deltaMigration
    ? [{
        migration: deltaMigration,
        containers: migrationContainers({}, deltaMigration),
      }]
    : [];
  const recipeContainers = [
    ...containers,
    ...deltaFallback.flatMap((fallback) => fallback.containers),
  ];

  return {
    general: buildGeneralInfo(details, migration, containers, deltaFallback),
    recipes: buildRecipes(recipeContainers),
  };
}
