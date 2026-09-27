export function recordedSalesOrderMoney(value: number | null | undefined, currency: string | null | undefined) {
  return value == null || !currency ? "—" : `${Number(value).toFixed(2)} ${currency}`;
}
