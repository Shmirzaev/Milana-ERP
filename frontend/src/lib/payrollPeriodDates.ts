const FACTORY_TIMEZONE = "Asia/Tashkent";

export function factoryMonth(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: FACTORY_TIMEZONE, year: "numeric", month: "2-digit" }).format(now);
}

export function monthStart(now = new Date()): string {
  return `${factoryMonth(now)}-01`;
}

export function monthEnd(now = new Date()): string {
  const [year, month] = factoryMonth(now).split("-").map(Number);
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

export function factoryPeriodIso(value: string, end = false): string {
  // Factory operations consistently use Asia/Tashkent (UTC+05:00).
  return new Date(`${value}T${end ? "23:59:59" : "00:00:00"}+05:00`).toISOString();
}
