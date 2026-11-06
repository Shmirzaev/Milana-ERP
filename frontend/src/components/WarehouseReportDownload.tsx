"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { fetchResponse } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { ApiError } from "@/lib/errorMessages";
import { useT } from "@/lib/i18n";

const labels = {
  en: "Download Excel report",
  ru: "Скачать отчёт Excel",
  uz: "Excel hisobotini yuklab olish",
};

export default function WarehouseReportDownload() {
  const { me } = useMe();
  const { lang, t } = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!can(me, "storage.packages", "storage.shipment")) return null;

  async function download() {
    setBusy(true);
    setError("");
    try {
      const response = await fetchResponse(`/api/packages/warehouse-report.xlsx?lang=${lang}`, { credentials: "same-origin" });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new ApiError(response.status, typeof payload?.detail === "string" ? payload.detail : "Request failed");
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "warehouse-stock.xlsx";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t("packagingReport.downloadFailed"));
    } finally {
      setBusy(false);
    }
  }

  return <div>
    <button type="button" className="btn" disabled={busy} onClick={download}>
      <Download className="h-4 w-4" aria-hidden="true" />
      {busy ? t("common.loading") : labels[lang]}
    </button>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
  </div>;
}
