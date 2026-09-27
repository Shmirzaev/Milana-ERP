export const RESET_PROXY_MAX_BODY_BYTES = 16 * 1024;

export class ResetProxyInputError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ResetProxyInputError";
  }
}

export async function readBoundedResetJson(
  request: Request,
  signal: AbortSignal,
): Promise<unknown> {
  const declaredLength = request.headers.get("content-length");
  if (declaredLength !== null) {
    const parsedLength = Number(declaredLength);
    if (!Number.isSafeInteger(parsedLength) || parsedLength < 0) {
      throw new ResetProxyInputError(400, "Invalid Content-Length");
    }
    if (parsedLength > RESET_PROXY_MAX_BODY_BYTES) {
      throw new ResetProxyInputError(413, "Request body too large");
    }
  }

  if (!request.body) {
    throw new ResetProxyInputError(400, "Invalid JSON");
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  const cancel = () => { void reader.cancel(); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    while (true) {
      if (signal.aborted) throw new ResetProxyInputError(408, "Request body timed out");
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > RESET_PROXY_MAX_BODY_BYTES) {
        await reader.cancel();
        throw new ResetProxyInputError(413, "Request body too large");
      }
      chunks.push(value);
    }
  } catch (error) {
    if (signal.aborted) throw new ResetProxyInputError(408, "Request body timed out");
    throw error;
  } finally {
    signal.removeEventListener("abort", cancel);
  }
  if (signal.aborted) throw new ResetProxyInputError(408, "Request body timed out");

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new ResetProxyInputError(400, "Invalid JSON");
  }
}
