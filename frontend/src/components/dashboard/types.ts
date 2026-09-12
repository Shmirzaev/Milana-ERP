export const stageKeys = ["cutting", "printing", "sewing", "packaging"] as const;
export type Stage = typeof stageKeys[number];
export type DailyOutput = { date: string } & Record<Stage, number>;
export type Overview = {
  start: string; end: string; updated_at: string; timezone: string;
  active_orders: number; late_orders: number; planned_quantity: number;
  by_status: Record<string, number>; totals: Record<Stage, number>; daily: DailyOutput[];
  orders: { id: number; order_no: string; type: string; source_type: string; status: string; qty: number; deadline: string | null }[];
  orders_limit: number;
};
export const stageColors = ["#c2410c", "#a88130", "#1f7a4d", "#7161a8"];
export function businessDate(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tashkent", year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
}
export function periodDates(days: number, today: string) {
  const start = new Date(`${today}T12:00:00Z`);
  start.setUTCDate(start.getUTCDate() - days + 1);
  return { start: start.toISOString().slice(0, 10), end: today };
}
