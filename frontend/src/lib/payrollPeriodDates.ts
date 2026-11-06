const FACTORY_TIMEZONE = "Asia/Tashkent";

export function factoryMonth(now = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: FACTORY_TIMEZONE, year: "numeric", month: "2-digit" }).format(now);
}

export function monthStart(now = new Date()): string {
  return `${factoryMonth(now)}-01`;
}

export function monthEnd(now = new Date()): string {
  const month = factoryMonth(now);
  return new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0)).toISOString().slice(0, 10);
}

export function factoryPeriodIso(value: string, end = false): string {
  // Factory operations consistently use Asia/Tashkent (UTC+05:00).
  return new Date(`${value}T${end ? "23:59:59" : "00:00:00"}+05:00`).toISOString();
}

export function formatFactoryPeriodDate(value: string, lang: string): string {
  return new Date(value).toLocaleDateString(lang, { timeZone: FACTORY_TIMEZONE });
}
