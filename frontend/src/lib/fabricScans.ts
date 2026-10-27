export type FabricDirection = "received" | "returned";
export type FabricScanRow = {
  id: number;
  report_date: string;
  direction: FabricDirection;
  fabric_name: string;
  batch_no: string;
  color: string | null;
  roll_number: number;
  operator_name: string;
  scanned_at: string;
};
export type FabricSummary = { fabric_name: string; batch_no: string; color: string | null; received: number; returned: number };
export type FabricReport = {
  report_date: string;
  department: string;
  received: number;
  returned: number;
  total: number;
  rows: FabricScanRow[];
  summary: FabricSummary[];
};
export const FABRIC_SCAN_PERMISSIONS = ["cutting.records", "cutting.bundles", "storage.receive", "storage.items"];
export const FABRIC_REPORT_PERMISSIONS = [...FABRIC_SCAN_PERMISSIONS, "planning.production", "management.view"];

export function isFabricRollCode(code: string) {
  const value = code.trim();
  if (/^B[1-9]\d*-R[1-9]\d*$/i.test(value)) return true;
  try {
    const url = new URL(value, "https://local.invalid");
    return url.pathname.replace(/\/$/, "") === "/inventory"
      && /^(https?:)$/.test(url.protocol)
      && /^[1-9]\d*$/.test(url.searchParams.get("batch_id") || "")
      && /^[1-9]\d*$/.test(url.searchParams.get("roll") || "");
  } catch { return false; }
}

export function tashkentDate() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function downloadFabricReport(data: FabricReport, t: (key: string) => string) {
  const cells = (values: (string | number | null)[]) => values.map((value) => {
    const text = String(value ?? "");
    const safe = /^[=+\-@\t\r\n]/.test(text) ? `'${text}` : text;
    return `"${safe.replace(/"/g, '""')}"`;
  }).join(",");
  const lines = [cells([t("fabricScans.date"), t("fabricScans.fabric"), t("fabricScans.batch"), t("fabricScans.color"), t("fabricScans.received"), t("fabricScans.returned")]),
    ...data.summary.map((row) => cells([data.report_date, row.fabric_name, row.batch_no, row.color, row.received, row.returned]))];
  const url = URL.createObjectURL(new Blob(["\uFEFF", lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `fabric-scans-${data.department}-${data.report_date}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
