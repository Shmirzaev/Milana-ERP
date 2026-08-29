export type OperationLabelIdentity = {
  id: string;
  code: string;
  name?: string;
  sourceOrder?: number;
};

const MAX_OPERATION_TOKEN_LENGTH = 24;

function compactOperationCode(value: string): string {
  const compacted = String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^0-9A-Z $%+\-./:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return (compacted || "-").slice(0, MAX_OPERATION_TOKEN_LENGTH);
}

function shortStableHash(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36).toUpperCase().padStart(7, "0").slice(-7);
}

/**
 * Builds stable operation tokens for payroll-label IDs.
 *
 * The first occurrence keeps the historical code-only token so already-issued
 * labels remain idempotent. Later occurrences of the same code receive a
 * stable discriminator derived from the operation's own identity.
 */
export function buildOperationLabelTokens(
  operations: OperationLabelIdentity[],
): Map<string, string> {
  const seenCodes = new Map<string, number>();
  const usedTokens = new Set<string>();
  const tokens = new Map<string, string>();

  for (const operation of operations) {
    const baseToken = compactOperationCode(operation.code);
    const occurrence = seenCodes.get(baseToken) || 0;
    seenCodes.set(baseToken, occurrence + 1);

    if (occurrence === 0 && !usedTokens.has(baseToken)) {
      tokens.set(operation.id, baseToken);
      usedTokens.add(baseToken);
      continue;
    }

    const identity = [operation.id, operation.name || "", operation.sourceOrder ?? ""].join("|");
    let attempt = 0;
    let token = "";
    do {
      const suffix = shortStableHash(attempt === 0 ? identity : `${identity}|${attempt}`);
      const prefix = baseToken.slice(0, MAX_OPERATION_TOKEN_LENGTH - suffix.length - 1);
      token = `${prefix}-${suffix}`;
      attempt += 1;
    } while (usedTokens.has(token));

    tokens.set(operation.id, token);
    usedTokens.add(token);
  }

  return tokens;
}
