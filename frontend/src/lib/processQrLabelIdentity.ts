export type OperationLabelIdentity = {
  id: string;
  code: string;
  name?: string;
  sourceOrder?: number;
  section?: string;
  rate?: string | number;
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
  issued: IssuedOperationIdentity[] = [],
): Map<string, string> {
  const seenCodes = new Map<string, number>();
  const usedTokens = new Set<string>();
  const tokens = new Map<string, string>();
  const owners = new Map<string, IssuedOperationIdentity[]>();
  for (const label of issued) {
    const token = issuedOperationToken(label);
    if (token) owners.set(token, [...(owners.get(token) || []), label]);
  }
  const available = (token: string, operation: OperationLabelIdentity) => (
    !usedTokens.has(token)
    && (owners.get(token) || []).every((label) => sameOperation(operation, label, operations))
  );

  const reuseExisting = (preferred: string, operation: OperationLabelIdentity): string => {
    if (owners.has(preferred)) return preferred;
    const matches = [...owners.entries()].filter(([token, labels]) => available(token, operation)
      && labels.every((label) => operations.filter((candidate) => sameOperation(candidate, label, operations)).length === 1));
    return matches.length === 1 ? matches[0]![0] : preferred;
  };

  for (const operation of operations) {
    const baseToken = compactOperationCode(operation.code);
    const occurrence = seenCodes.get(baseToken) || 0;
    seenCodes.set(baseToken, occurrence + 1);

    if (occurrence === 0 && available(baseToken, operation)) {
      const token = reuseExisting(baseToken, operation);
      tokens.set(operation.id, token);
      usedTokens.add(token);
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
    } while (!available(token, operation));

    token = reuseExisting(token, operation);
    tokens.set(operation.id, token);
    usedTokens.add(token);
  }

  return tokens;
}

export type IssuedOperationIdentity = {
  id: number;
  label_uid: string;
  operation_code?: string | null;
  operation_name?: string | null;
  operation_section?: string | null;
  rate_per_piece?: number | string;
  payload?: string | null;
  split_from_label_id?: number | null;
};

/** PY identifiers end with factory, line, size and copy; the operation may contain colons. */
export function issuedOperationToken(label: IssuedOperationIdentity): string | null {
  const parts = label.label_uid.split(":");
  return parts[0] === "PY" && parts.length >= 9 ? parts.slice(4, -4).join(":") : null;
}

const normalized = (value: string | null | undefined) => String(value || "").trim().toLocaleLowerCase();
function sameOperation(operation: OperationLabelIdentity, label: IssuedOperationIdentity, operations: OperationLabelIdentity[]): boolean {
  return (
    normalized(operation.code) === normalized(label.operation_code)
    && normalized(operation.name) === normalized(label.operation_name)
    && (!operation.section || normalized(operation.section) === normalized(label.operation_section))
    && (operations.filter((candidate) => normalized(candidate.code) === normalized(operation.code)
      && normalized(candidate.name) === normalized(operation.name)
      && normalized(candidate.section) === normalized(operation.section)).length < 2
      || label.payload === null
      || Number(operation.rate || 0) === Number(label.rate_per_piece || 0))
  );
}

/** Number immutable issued identities, keeping historical extras separate from current model rows. */
export function buildIssuedOperationNumbers(
  operations: OperationLabelIdentity[],
  issued: IssuedOperationIdentity[],
  tokens = buildOperationLabelTokens(operations, issued),
): Map<number, number> {
  const numbers = new Map<number, number>();
  const historical = new Map<string, number>();
  let nextNumber = operations.length + 1;
  for (const label of [...issued].sort((left, right) => left.id - right.id)) {
    const parentNumber = label.split_from_label_id ? numbers.get(label.split_from_label_id) : undefined;
    if (parentNumber !== undefined) {
      numbers.set(label.id, parentNumber);
      continue;
    }
    const token = issuedOperationToken(label);
    const index = operations.findIndex((operation) => tokens.get(operation.id) === token && sameOperation(operation, label, operations));
    if (index >= 0) {
      numbers.set(label.id, index + 1);
      continue;
    }
    const key = JSON.stringify([token || label.label_uid, normalized(label.operation_code), normalized(label.operation_name), normalized(label.operation_section), Number(label.rate_per_piece || 0)]);
    if (!historical.has(key)) historical.set(key, nextNumber++);
    numbers.set(label.id, historical.get(key)!);
  }
  return numbers;
}

/** A renamed correction has no original operation snapshot. Do not infer a new payable identity. */
export function correctedOperationIdentityNeedsReview(
  operations: OperationLabelIdentity[], issued: IssuedOperationIdentity[],
): boolean {
  const currentTokens = new Set(buildOperationLabelTokens(operations).values());
  return issued.some((label) => label.payload === null
    && currentTokens.has(issuedOperationToken(label) || "")
    && !operations.some((operation) => sameOperation(operation, label, operations)));
}
