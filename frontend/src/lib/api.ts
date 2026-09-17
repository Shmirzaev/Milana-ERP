function errorDetail(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(errorDetail).filter(Boolean).join("; ");
  if (!value || typeof value !== "object") return "";
  const error = value as Record<string, unknown>;
  const message = errorDetail(error.detail) || errorDetail(error.message) || errorDetail(error.msg);
  if (!message) return "";
  const path = Array.isArray(error.loc)
    ? error.loc.filter((part) => part !== "body" && part !== "query" && part !== "path")
      .map((part) => typeof part === "number" ? `[${part + 1}]` : String(part).replaceAll("_", " "))
      .join(" / ")
    : "";
  return path ? `${path}: ${message}` : message;
}

function resolveUrl(path: string): string {
  if (path.startsWith("http")) return path;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return normalized;
}


async function fetchWithTimeout<T>(
  url: string, init: RequestInit, timeoutMs: number, consume: (response: Response) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const callerSignal = init.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) abortFromCaller();
  else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { credentials: "same-origin", ...init, signal: controller.signal });
    // fetch resolves at headers. Keep cancellation active until the body is read.
    const result = await consume(response);
    controller.signal.throwIfAborted();
    return result;
  } catch (err: any) {
    if (controller.signal.aborted || err?.name === "AbortError") {
      if (callerSignal?.aborted) callerSignal.throwIfAborted();
      throw new Error(
        `Backend is not responding. Check backend server and frontend API proxy settings (NEXT_PUBLIC_API_URL/API_URL). Request: ${url}`
      );
    }
    throw err;
  } finally {
    clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = errorDetail(await res.json()) || detail || "Request failed";
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isTransientNetworkError(message: string): boolean {
  const m = (message || "").toLowerCase();
  return (
    m.includes("backend is not responding") ||
    m.includes("failed to fetch") ||
    m.includes("networkerror") ||
    m.includes("network error") ||
    m.includes("bad gateway") ||
    m.includes("gateway timeout") ||
    m.includes("service unavailable")
  );
}

function clearLegacyToken() {
  if (typeof window !== "undefined") {
    // Auth is cookie-only. Remove any stale pre-migration browser-readable JWT.
    localStorage.removeItem("erp_token");
  }
}

export function setToken(_token: string) {
  void _token;
  clearLegacyToken();
}

export function clearToken() {
  clearLegacyToken();
}

async function request<T = any>(path: string, init: RequestInit = {}, timeoutMs = 12_000): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };

  // Use Next.js rewrite proxy: paths starting with /api or /storage are proxied
  const url = resolveUrl(path);
  return fetchWithTimeout(url, { ...init, headers }, timeoutMs, readJson<T>);
}

export const api = {
  get: <T = any>(p: string, timeoutMs?: number) => request<T>(p, { method: "GET" }, timeoutMs),
  getWithSignal: <T = any>(p: string, signal: AbortSignal, timeoutMs?: number) =>
    request<T>(p, { method: "GET", signal }, timeoutMs),
  post: <T = any>(p: string, body?: any, timeoutMs?: number) =>
    request<T>(p, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }, timeoutMs),
  postWithIdempotency: <T = any>(p: string, body: unknown, key: string, timeoutMs?: number) =>
    request<T>(p, { method: "POST", headers: { "Idempotency-Key": key }, body: JSON.stringify(body) }, timeoutMs),
  postForm: async <T = any>(p: string, form: FormData, timeoutMs = 60_000): Promise<T> => {
    return fetchWithTimeout(resolveUrl(p), { method: "POST", body: form }, timeoutMs, readJson<T>);
  },
  patch: <T = any>(p: string, body?: any) =>
    request<T>(p, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T = any>(p: string, body?: any) =>
    request<T>(p, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  del: <T = any>(p: string, body?: unknown) => request<T>(p, { method: "DELETE", body: body !== undefined ? JSON.stringify(body) : undefined }),

  async login(email: string, password: string, factoryCode: "MIL" | "BST" | "ECO"): Promise<void> {
    const loginEndpoints = [
      resolveUrl("/api/auth/login-json"),
    ];
    const maxAttempts = 3;
    let lastTransientError = "";
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      for (const endpoint of loginEndpoints) {
        try {
          const res = await fetchWithTimeout(
            endpoint,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ email, password, factory_code: factoryCode }),
            },
            20_000,
            async (response) => {
              let msg = "Login failed";
              if (response.ok) {
                await response.arrayBuffer();
              } else {
                try {
                  if ((response.headers.get("content-type") || "").includes("application/json")) {
                    msg = errorDetail(await response.json()) || msg;
                  } else {
                    msg = (await response.text()).trim().slice(0, 300) || msg;
                  }
                } catch {}
              }
              return { ok: response.ok, status: response.status, msg };
            },
          );
          if (res.ok) {
            clearLegacyToken();
            return;
          }

          const msg = res.msg;

          const shouldRetry =
            res.status === 500 || res.status === 502 || res.status === 503 || res.status === 504;
          if (shouldRetry) {
            lastTransientError = `${res.status}: ${msg}`;
            continue;
          }
          throw new Error(msg);
        } catch (err: any) {
          const message = String(err?.message || "");
          if (isTransientNetworkError(message)) {
            lastTransientError = message;
            continue;
          }
          throw err;
        }
      }
      if (attempt < maxAttempts) await sleep(1200 * attempt);
    }
    throw new Error(
      lastTransientError ? `Backend is not responding (${lastTransientError})` : "Login failed",
    );
  },

  async forgotPassword(email: string): Promise<{ message: string }> {
    return fetchWithTimeout(
      resolveUrl("/api/auth/forgot-password"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      },
      60_000,
      readJson<{ message: string }>,
    );
  },

  async resetPassword(token: string, newPassword: string, confirmNewPassword: string): Promise<{ message: string }> {
    return fetchWithTimeout(
      resolveUrl("/api/auth/reset-password"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          new_password: newPassword,
          confirm_new_password: confirmNewPassword,
        }),
      },
      60_000,
      readJson<{ message: string }>,
    );
  },

  async logout() {
    clearToken();
    try {
      await fetchWithTimeout(resolveUrl("/api/auth/logout"), { method: "POST" }, 8_000, async (res) => { await res.arrayBuffer(); });
    } catch {}
  },

  /**
   * Fetches an HTML label endpoint with the HttpOnly cookie and opens it in a
   * new window for printing. We pull the HTML ourselves and inject it into a
   * child window via a Blob URL so the print view does not need bearer tokens.
   */
  async openLabel(path: string, method: "GET" | "POST" = "GET"): Promise<void> {
    const html = await fetchWithTimeout(resolveUrl(path), { method }, 12_000, async (res) => {
      if (!res.ok) await readJson(res);
      return res.text();
    });
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const win = window.open(url, "_blank", "width=600,height=700");
    if (!win) {
      // Popup blocked — fall back to same-tab open.
      window.location.href = url;
    }
    // Revoke later so the new window has time to load the document.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  },
};

export const fetcher = <T = any>(url: string) => api.get<T>(url);
