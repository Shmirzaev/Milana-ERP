import Constants from "expo-constants";

import { normalizeBaseUrl } from "../api/client";

function configuredWebBaseUrl() {
  return process.env.EXPO_PUBLIC_ERP_WEB_URL || Constants.expoConfig?.extra?.erpWebUrl || "";
}

function inferLocalWebUrl(apiBaseUrl: string) {
  return normalizeBaseUrl(apiBaseUrl).replace(/:8000$/, ":3000");
}

export function buildErpWebUrl(apiBaseUrl: string, path = "/") {
  const base = configuredWebBaseUrl() || inferLocalWebUrl(apiBaseUrl);
  const normalizedBase = normalizeBaseUrl(base || "http://localhost:3000");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`;
}
