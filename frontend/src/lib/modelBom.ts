// Mirrors the backend canonical BOM material-role enum: app/libs/enums/catalog.py (BomMaterialRole).
// A manual Usluga fabric is either the main material or a secondary one.
export type BomMaterialRole = "main" | "secondary";

export const BOM_MATERIAL_ROLE_MAIN: BomMaterialRole = "main";
export const BOM_MATERIAL_ROLE_SECONDARY: BomMaterialRole = "secondary";
export const BOM_MATERIAL_ROLES: BomMaterialRole[] = [
  BOM_MATERIAL_ROLE_MAIN,
  BOM_MATERIAL_ROLE_SECONDARY,
];

// The BOM create request body. An inventory-linked line carries the item
// reference; a manual Usluga fabric carries the name and the role.
export type BomCreatePayload = {
  item_id: number | null;
  material_name?: string | null;
  material_role?: BomMaterialRole | null;
  stock_batch_id: number | null;
  size: string | null;
  color: string | null;
  photo_url: string | null;
  quantity_per_piece: number;
  unit: string;
  waste_percent: number;
};

// The create operation answers with the new row id and nothing else.
export type BomCreateResult = { id: number };
