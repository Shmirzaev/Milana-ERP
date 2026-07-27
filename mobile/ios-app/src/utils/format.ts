import type { Entity, ListEnvelope } from "../types/api";

export function humanizeKey(key: string) {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatDate(value: unknown) {
  if (!value) return "";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatMoney(value: unknown) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "";
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}/.test(value)) return formatDate(value);
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === "object") return "View details";
  return String(value);
}

export function firstPresent(entity: Entity, keys: string[]) {
  for (const key of keys) {
    const value = entity[key];
    if (value !== null && value !== undefined && value !== "") return value;
  }
  return undefined;
}

export function normalizeRows(data: unknown): Entity[] {
  if (Array.isArray(data)) return data as Entity[];
  const envelope = data as ListEnvelope | null;
  if (Array.isArray(envelope?.rows)) return envelope.rows;
  if (Array.isArray(envelope?.items)) return envelope.items;
  if (data && typeof data === "object") return [data as Entity];
  return [];
}

export function matchesQuery(entity: Entity, query: string) {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return Object.values(entity).some((value) => String(value ?? "").toLowerCase().includes(needle));
}

export function compactParts(parts: unknown[]) {
  return parts.map(formatValue).filter((part) => part && part !== "-").join(" · ");
}
