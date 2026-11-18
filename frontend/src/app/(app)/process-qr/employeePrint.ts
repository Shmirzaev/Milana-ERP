export async function prepareEmployeePrintRows<T extends { payload: string }>(
  rows: T[],
  encode: (payload: string) => Promise<string>,
): Promise<Array<T & { qrImage: string }>> {
  const images = new Map<string, Promise<string>>();
  for (const row of rows) {
    if (!images.has(row.payload)) images.set(row.payload, encode(row.payload));
  }
  return Promise.all(rows.map(async (row) => ({ ...row, qrImage: await images.get(row.payload)! })));
}
