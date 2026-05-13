const defaultApiBase =
  process.env.NODE_ENV === "production" ? "https://milana-erp.onrender.com" : "";
const API_BASE = String(process.env.NEXT_PUBLIC_API_URL || process.env.API_URL || defaultApiBase || "")
  .trim()
  .replace(/\/+$/, "");

function resolveUrl(path: string): string {
  if (path.startsWith("http")) return path;
  if (API_BASE && path.startsWith("/")) return `${API_BASE}${path}`;
  return path;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("erp_token");
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
  const res = await fetch(url, { ...init, headers });
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
  patch: <T = any>(p: string, body?: any) =>
    request<T>(p, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  del: <T = any>(p: string) => request<T>(p, { method: "DELETE" }),

  async login(email: string, password: string): Promise<string> {
    const form = new URLSearchParams();
    form.set("username", email);
    form.set("password", password);
    const res = await fetch(resolveUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form.toString(),
    });
    if (!res.ok) {
      let msg = "Login failed";
      try {
        const b = await res.json();
        msg = b.detail || msg;
      } catch {}
      throw new Error(msg);
    }
    const body = await res.json();
    setToken(body.access_token);
    return body.access_token;
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
    const res = await fetch(resolveUrl(path), {
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
