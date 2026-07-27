export type NumberInputValue = number | "";

export function parseNumberInput(value: string): NumberInputValue {
  return value === "" ? "" : Number(value);
}

export function numberOrZero(value: unknown): number {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function numberOrFallback(value: unknown, fallback: number): number {
  if (value === "" || value === null || value === undefined) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
