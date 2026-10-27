export function divideBatchQuantityByRollCount(batchQuantity: number, rollCount: number) {
  const count = Math.max(1, Math.floor(Number(rollCount) || 1));
  const totalHundredths = Math.max(0, Math.round((Number(batchQuantity) || 0) * 100));
  const baseHundredths = Math.floor(totalHundredths / count);
  const remainder = totalHundredths - baseHundredths * count;

  return Array.from({ length: count }, (_, index) => (
    (baseHundredths + (index < remainder ? 1 : 0)) / 100
  ));
}
