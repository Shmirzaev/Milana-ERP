/** Unsaved ECO sources use an isolated local selection key. It is never an FK
 * or API identity: every write encodes the explicit ECO source field instead. */
export function fabricSelectionRows<T extends { id: number | null; eco_material_batch_id?: number | null }>(rows: T[]): Array<T & { id: number }> {
  return rows.map(row => ({ ...row, id: row.id ?? -Number(row.eco_material_batch_id) }));
}

export function fabricSourceInput(selectionId: number) {
  return selectionId < 0
    ? { stock_batch_id: null, eco_material_batch_id: -selectionId }
    : { stock_batch_id: selectionId, eco_material_batch_id: null };
}

export function primaryFabricSourceInput(selectionId: number) {
  return selectionId < 0
    ? { fabric_batch_id: null, eco_fabric_batch_id: -selectionId }
    : { fabric_batch_id: selectionId, eco_fabric_batch_id: null };
}
