function resolveUrl(path: string): string {
  if (path.startsWith("http")) return path;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return normalized;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("erp_token");
}

async function fetchWithTimeout(url: string, init: RequestInit = {}, timeoutMs = 12_000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err: any) {
    if (err?.name === "AbortError") {
      throw new Error(
        `Backend is not responding. Check backend server and frontend API proxy settings (NEXT_PUBLIC_API_URL/API_URL). Request: ${url}`
      );
    }
    throw err;
  } finally {
    clearTimeout(timeout);
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

export function setToken(token: string) {
  if (typeof window !== "undefined") {
    localStorage.setItem("erp_token", token);
  }
}

export function clearToken() {
  if (typeof window !== "undefined") {
    localStorage.removeItem("erp_token");
  }
}

async function request<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  // Use Next.js rewrite proxy: paths starting with /api or /storage are proxied
  const url = resolveUrl(path);
  const res = await fetchWithTimeout(url, { ...init, headers });
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
  get: <T = any>(p: string) => request<T>(p, { method: "GET" }),
  post: <T = any>(p: string, body?: any) =>
    request<T>(p, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  postForm: async <T = any>(p: string, form: FormData): Promise<T> => {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetchWithTimeout(resolveUrl(p), { method: "POST", body: form, headers });
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
  del: <T = any>(p: string) => request<T>(p, { method: "DELETE" }),

  async login(email: string, password: string): Promise<string> {
    const form = new URLSearchParams();
    form.set("username", email);
    form.set("password", password);
    const loginEndpoints = [
      resolveUrl("/api/auth/login"),
      "https://milana-erp.onrender.com/api/auth/login",
    ];
    const maxAttempts = 3;
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      for (const endpoint of loginEndpoints) {
        try {
          const res = await fetchWithTimeout(
            endpoint,
            {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded" },
              body: form.toString(),
            },
            20_000,
          );
          if (res.ok) {
            const body = await res.json();
            setToken(body.access_token);
            return body.access_token;
          }

          let msg = "Login failed";
          try {
            const b = await res.json();
            msg = b.detail || msg;
          } catch {}

          const shouldRetry =
            res.status === 500 || res.status === 502 || res.status === 503 || res.status === 504;
          if (shouldRetry) {
            continue;
          }
          throw new Error(msg);
        } catch (err: any) {
          const message = String(err?.message || "");
          if (isTransientNetworkError(message)) {
            continue;
          }
          throw err;
        }
      }
      if (attempt < maxAttempts) await sleep(1200 * attempt);
    }
    throw new Error("Login failed");
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

  logout() {
    clearToken();
  },

  /**
   * Fetches an HTML label endpoint with the auth header attached and opens it
   * in a new window for printing. Browsers won't send the JWT on a bare
   * `target="_blank"` link, so we have to pull the HTML ourselves and inject it
   * into a child window via a Blob URL.
   */
  async openLabel(path: string): Promise<void> {
    const token = getToken();
    const res = await fetchWithTimeout(resolveUrl(path), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
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
