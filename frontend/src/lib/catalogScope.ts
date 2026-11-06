// Mirrors the backend canonical scope enum: app/libs/enums/catalog.py (CatalogScope).
// It selects the owning paid-process table and the Eco Cotton access rule.
export type CatalogScope = "standard" | "usluga";

export const CATALOG_SCOPES: CatalogScope[] = ["standard", "usluga"];

export const DEFAULT_CATALOG_SCOPE: CatalogScope = "standard";
