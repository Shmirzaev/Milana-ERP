import Constants from "expo-constants";

export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

type RequestOptions = {
  method?: HttpMethod;
  body?: unknown;
  token?: string | null;
  baseUrl?: string | null;
  headers?: Record<string, string>;
  timeoutMs?: number;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const DEFAULT_API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  Constants.expoConfig?.extra?.apiBaseUrl ||
  "http://localhost:8000";

export function normalizeBaseUrl(value?: string | null) {
  const raw = (value || DEFAULT_API_BASE_URL).trim();
  return raw.replace(/\/+$/, "");
}

function buildUrl(path: string, baseUrl?: string | null) {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizeBaseUrl(baseUrl)}${normalizedPath}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  if (!text) return undefined as T;
  if (contentType.includes("application/json")) {
    return JSON.parse(text) as T;
  }
  return text as T;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 15000);
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...options.headers,
  };

  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }

  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  try {
    const response = await fetch(buildUrl(path, options.baseUrl), {
      method: options.method || "GET",
      headers,
      body,
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = response.statusText || "Request failed";
      try {
        const parsed = await parseResponse<any>(response);
        message = parsed?.detail || parsed?.message || JSON.stringify(parsed) || message;
      } catch {
        // Keep the HTTP status text when error payload parsing fails.
      }
      throw new ApiError(response.status, message);
    }

    return parseResponse<T>(response);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Backend did not respond before the mobile request timed out.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function loginWithPassword(baseUrl: string, email: string, password: string) {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);

  return request<{ access_token: string; token_type: string }>("/api/auth/token", {
    method: "POST",
    baseUrl,
    body: form.toString(),
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    timeoutMs: 20000,
  });
}
