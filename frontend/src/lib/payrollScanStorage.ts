export const PAYROLL_SCAN_STORAGE_KEY = "milana_payroll_scan_records_v2";

type StoredPayrollScanRecord = {
  workKey?: unknown;
  scanUid?: unknown;
  rawWork?: {
    label_id?: unknown;
  } | null;
};

export function payrollScanRecordMatchesLabel(record: StoredPayrollScanRecord, labelUid: string): boolean {
  const normalizedLabelUid = String(labelUid || "").trim();
  if (!normalizedLabelUid) return false;

  const workKey = String(record.workKey || "").trim();
  const scanUid = String(record.scanUid || "").trim();
  const rawLabelUid = String(record.rawWork?.label_id || "").trim();
  return workKey === normalizedLabelUid
    || scanUid === normalizedLabelUid
    || scanUid === `payroll:${normalizedLabelUid}`
    || rawLabelUid === normalizedLabelUid;
}

export function removePayrollScanHistoryForLabel(labelUid: string, storage: Storage): number {
  const saved = storage.getItem(PAYROLL_SCAN_STORAGE_KEY);
  if (!saved) return 0;

  let parsed: unknown;
  try {
    parsed = JSON.parse(saved);
  } catch {
    return 0;
  }
  if (!Array.isArray(parsed)) return 0;

  const remaining = parsed.filter((record) => (
    !record
    || typeof record !== "object"
    || !payrollScanRecordMatchesLabel(record as StoredPayrollScanRecord, labelUid)
  ));
  const removedCount = parsed.length - remaining.length;
  if (removedCount > 0) {
    storage.setItem(PAYROLL_SCAN_STORAGE_KEY, JSON.stringify(remaining));
  }
  return removedCount;
}
