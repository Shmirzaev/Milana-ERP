import { DailyOutput, Factory, factoryCodes, factoryNames, Overview, Stage, stageKeys } from "./types";

// Operational dashboards use API data. Retain fixtures for isolated presentation tests.
export const dashboardDemoEnabled = false;
export const demoFinance = { revenue_total: 428650, payments_received: 386420 };
export const demoMessages = {
  en: { label: "Demo data", note: "Illustrative figures for all three factories. This dashboard does not show live production or financial data.", generated: "Demo generated" },
  ru: { label: "Демо-данные", note: "Примерные показатели трёх фабрик. Эта панель не отображает реальные производственные и финансовые данные.", generated: "Демо сформировано" },
  uz: { label: "Demo ma’lumotlar", note: "Uchta fabrika uchun namunaviy ko‘rsatkichlar. Bu panel haqiqiy ishlab chiqarish va moliyaviy ma’lumotlarni ko‘rsatmaydi.", generated: "Demo yaratildi" },
};

type FactoryCode = Exclude<Factory, "ALL">;
const reportValues: Record<FactoryCode, number[]> = {
  MIL: [4260, 4680, 4450, 5120, 4870, 5360, 5640],
  BST: [2840, 3120, 2960, 3340, 3210, 3690, 3860],
  ECO: [1780, 1960, 1830, 2240, 2090, 2390, 2560],
};
const counts = [32, 24, 16];
const statuses = [
  ["sewing", "planning", "cutting", "packaging", "printing", "sewing", "storage_transfer", "sewing"],
  ["cutting", "sewing", "planning", "packaging", "sewing", "printing", "sewing", "planning"],
  ["packaging", "sewing", "cutting", "planning", "printing", "sewing", "storage_transfer", "sewing"],
];
function shiftDate(day: string, offset: number) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}
function stageTotals(daily: DailyOutput[]): Record<Stage, number> {
  return {
    cutting: daily.reduce((sum, row) => sum + row.cutting, 0),
    printing: daily.reduce((sum, row) => sum + row.printing, 0),
    sewing: daily.reduce((sum, row) => sum + row.sewing, 0),
    packaging: daily.reduce((sum, row) => sum + row.packaging, 0),
  };
}
function byStatus(orders: Overview["orders"]) {
  return orders.reduce<Record<string, number>>((result, order) => {
    result[order.status] = (result[order.status] || 0) + 1;
    return result;
  }, {});
}

export function demoOverview(start: string, end: string, factory: Factory, today: string): Overview {
  const days = Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1;
  const allOrders: Overview["orders"] = factoryCodes.flatMap((code, f) =>
    Array.from({ length: counts[f] }, (_, i) => ({
      id: -(f * 100 + i + 1),
      order_no: `${code}-${String(120 + i).padStart(4, "0")}`,
      type: ["client_order", "branded_stock", "service_order"][i % 3],
      source_type: "demo",
      qty: 1200 + ((i * 3 + f * 2) % 9) * 400,
      status: statuses[f][i % 8],
      deadline: `${shiftDate(today, i === 0 || (f === 0 && i === 1) ? -1 : 2 + i % 14)}T12:00:00Z`,
      factories: [code],
    })),
  );
  const samples = factoryCodes.map((code, f) => {
    const orders = allOrders.filter(order => order.factories[0] === code);
    const daily = Array.from({ length: days }, (_, i) => {
      // Anchor samples to calendar days so overlapping date windows agree.
      const date = shiftDate(start, i);
      const index = ((Math.round((Date.parse(date) - Date.parse(today)) / 86400000) + 6) % 7 + 7) % 7;
      const value = reportValues[code][index];
      return { date, report: value,
        cutting: Math.round(value * (1.25 + 0.08 * Math.sin(index + f))),
        printing: Math.round(value * (0.52 + 0.05 * Math.cos(index))),
        sewing: Math.round(value * 0.93),
        packaging: Math.round(value * (0.79 + 0.03 * Math.cos(index + f))),
      };
    });
    return { code, name: factoryNames[code], active_orders: orders.length,
      planned_quantity: orders.reduce((sum, order) => sum + order.qty, 0),
      late_orders: orders.filter(order => order.deadline!.slice(0, 10) < today).length,
      by_status: byStatus(orders), daily, totals: stageTotals(daily),
    };
  });
  const selected = samples.filter(row => factory === "ALL" || row.code === factory);
  const daily = samples[0].daily.map((row, i) => {
    const point: DailyOutput = { date: row.date, cutting: 0, printing: 0, sewing: 0, packaging: 0 };
    for (const key of stageKeys) point[key] = selected.reduce((sum, sample) => sum + sample.daily[i][key], 0);
    return point;
  });
  const reportDaily = daily.map((row, i) => ({ date: row.date, values: Object.fromEntries(samples.map(sample =>
    [sample.code, factory === "ALL" || sample.code === factory ? sample.daily[i].report : 0],
  )) }));
  const orders = allOrders.filter(order => factory === "ALL" || order.factories[0] === factory)
    .sort((a, b) => a.deadline!.localeCompare(b.deadline!) || Math.abs(a.id) % 100 - Math.abs(b.id) % 100 || b.id - a.id);
  return {
    start, end, updated_at: new Date().toISOString(), timezone: "Asia/Tashkent", factory,
    active_orders: orders.length, late_orders: selected.reduce((sum, row) => sum + row.late_orders, 0),
    planned_quantity: orders.reduce((sum, order) => sum + order.qty, 0), by_status: byStatus(orders),
    factories: samples, unassigned_orders: 0, unassigned_output: stageTotals([]),
    daily, totals: stageTotals(daily), orders, orders_limit: 100,
    sewing_reports: { daily: reportDaily, totals: {
      MIL: reportDaily.reduce((sum, row) => sum + row.values.MIL, 0),
      BST: reportDaily.reduce((sum, row) => sum + row.values.BST, 0),
      ECO: reportDaily.reduce((sum, row) => sum + row.values.ECO, 0),
    } },
  };
}
