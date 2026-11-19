/** Inclusive calendar boundaries in the same timezone as the shipment report. */
export function shipmentReportDates(period: "day" | "month", now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(item => item.type === type)!.value;
  const year = part("year"), month = part("month"), day = part("day");
  const today = `${year}-${month}-${day}`;
  if (period === "day") return { from: today, to: today };
  const last = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
  return { from: `${year}-${month}-01`, to: `${year}-${month}-${String(last).padStart(2, "0")}` };
}
