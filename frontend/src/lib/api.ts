function resolveUrl(path: string): string {
  if (path.startsWith("http")) return path;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return normalized;
}


async function fetchWithTimeout(url: string, init: RequestInit = {}, timeoutMs = 12_000) {
  const controller = new AbortController();
  const callerSignal = init.signal;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) abortFromCaller();
  else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { credentials: "same-origin", ...init, signal: controller.signal });
  } catch (err: any) {
    if (err?.name === "AbortError") {
      if (callerSignal?.aborted) throw err;
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
  const res = await fetchWithTimeout(url, { ...init, headers }, timeoutMs);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as any;
  return res.json();
}

export const api = {
  get: <T = any>(p: string, timeoutMs?: number) => request<T>(p, { method: "GET" }, timeoutMs),
  getWithSignal: <T = any>(p: string, signal: AbortSignal, timeoutMs?: number) =>
    request<T>(p, { method: "GET", signal }, timeoutMs),
  post: <T = any>(p: string, body?: any, timeoutMs?: number) =>
    request<T>(p, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }, timeoutMs),
  postForm: async <T = any>(p: string, form: FormData, timeoutMs = 60_000): Promise<T> => {
    const res = await fetchWithTimeout(resolveUrl(p), { method: "POST", body: form }, timeoutMs);
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch {}
      throw new Error(`${res.status}: ${detail}`);
    }
    if (res.status === 204) return undefined as any;
    return res.json();
  },
  patch: <T = any>(p: string, body?: any) =>
    request<T>(p, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T = any>(p: string, body?: any) =>
    request<T>(p, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  del: <T = any>(p: string) => request<T>(p, { method: "DELETE" }),

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
          );
          if (res.ok) {
            clearLegacyToken();
            return;
          }

          let msg = "Login failed";
          try {
            const contentType = res.headers.get("content-type") || "";
            if (contentType.includes("application/json")) {
              const b = await res.json();
              msg = b.detail || b.message || JSON.stringify(b) || msg;
            } else {
              const text = (await res.text()).trim();
              if (text) msg = text.slice(0, 300);
            }
          } catch {}

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
    const res = await fetchWithTimeout(
      resolveUrl("/api/auth/forgot-password"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      },
      60_000,
    );
    if (!res.ok) {
      let msg = "Could not send reset request";
      try {
        const body = await res.json();
        msg = body.detail || body.message || msg;
      } catch {}
      throw new Error(`${res.status}: ${msg}`);
    }
    return res.json();
  },

  async resetPassword(token: string, newPassword: string, confirmNewPassword: string): Promise<{ message: string }> {
    const res = await fetchWithTimeout(
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
    );
    if (!res.ok) {
      let msg = "Could not reset password";
      try {
        const body = await res.json();
        msg = body.detail || body.message || msg;
      } catch {}
      throw new Error(`${res.status}: ${msg}`);
    }
    return res.json();
  },

  async logout() {
    clearToken();
    try {
      await fetchWithTimeout(resolveUrl("/api/auth/logout"), { method: "POST" }, 8_000);
    } catch {}
  },

  /**
   * Fetches an HTML label endpoint with the HttpOnly cookie and opens it in a
   * new window for printing. We pull the HTML ourselves and inject it into a
   * child window via a Blob URL so the print view does not need bearer tokens.
   */
  async openLabel(path: string): Promise<void> {
    const res = await fetchWithTimeout(resolveUrl(path));
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || JSON.stringify(body);
      } catch {}
      throw new Error(`${res.status}: ${detail}`);
    }
    const html = await res.text();
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
