"use client";

import { useEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { localizeError } from "@/lib/errorMessages";
import ModelAsyncSelect from "@/components/ModelAsyncSelect";
import { paidOperationsForModelCopy, type PaidOperation, type PaidOperationFactory } from "@/lib/modelPaidOperations";

export default function ModelPaidOperationsCopy({ targetId, isUsluga, factories, onCopy }: {
  targetId: number;
  isUsluga: boolean;
  factories: PaidOperationFactory[];
  onCopy: (rows: PaidOperation[]) => void;
}) {
  const { t, lang } = useT();
  const [sourceId, setSourceId] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const mounted = useRef(true);
  const busy = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function copy() {
    if (!sourceId || sourceId === targetId || busy.current) return;
    busy.current = true;
    setLoading(true); setError(""); setCopied(false);
    try {
      const model = await api.get<{ details_json?: Record<string, unknown> }>(`${isUsluga ? "/api/usluga/models" : "/api/models"}/${sourceId}`);
      if (!mounted.current) return;
      const rows = paidOperationsForModelCopy(model.details_json, factories);
      if (!rows.length) { setError(t("page.modelDetail.copyOperationsEmpty")); return; }
      onCopy(rows);
      setCopied(true);
    } catch (caught) {
      if (mounted.current) setError(localizeError(caught instanceof Error ? caught.message : String(caught), 0, lang));
    } finally {
      busy.current = false;
      if (mounted.current) setLoading(false);
    }
  }

  return <div className="space-y-2 border-b border-[#ecebe3] pb-4">
    <label className="label" htmlFor="paid-operations-source">{t("page.modelDetail.copyOperationsFrom")}</label>
    <div className="flex flex-col gap-2 sm:flex-row">
      <div className="min-w-0 flex-1">
        <ModelAsyncSelect inputId="paid-operations-source" value={sourceId}
          onChange={(value) => { setSourceId(value); setError(""); setCopied(false); }}
          endpoint={isUsluga ? "/api/usluga/model-options" : "/api/model-options"}
          placeholder={t("newso.selectModel")} noResultsText={t("page.models.empty")}
          loadingText={t("common.loading")} loadMoreText={t("common.loadMore")} disabled={loading} />
      </div>
      <button type="button" className="btn" disabled={loading || !sourceId || sourceId === targetId} onClick={() => void copy()}>
        <Copy />{t(loading ? "common.loading" : "page.modelDetail.copyAllOperations")}
      </button>
    </div>
    <p className="text-xs text-[#56503f]">{t("page.modelDetail.copyOperationsHelp")}</p>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {copied && <p role="status" className="text-sm text-green-700">{t("page.modelDetail.copyOperationsReady")}</p>}
  </div>;
}
