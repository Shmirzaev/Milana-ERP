/** Presentation only: never use this value as a database key or scan payload. */
export function formatVariantNumber(raw: unknown): string {
  const value = String(raw ?? "").trim();
  if (!value || value === "—" || value === "-") return "";
  const number = value.replace(/^(?:V\s*[-=]\s*)+/i, "").trim();
  return number ? `V-${number}` : "";
}

/** Format a combined model/variant label only when its numeric suffix is clear. */
export function formatModelVariantCode(raw: unknown): string {
  const code = String(raw ?? "").trim();
  const parts = code.match(/^(.+\d.*?)-((?:V\s*[-=]\s*)?\d[^\s]*)$/i);
  return parts ? `${parts[1]}-${formatVariantNumber(parts[2])}` : code;
}
