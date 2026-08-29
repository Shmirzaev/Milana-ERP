"use client";

import { useRef, useState } from "react";
import { Plus } from "lucide-react";
import useSWR from "swr";
import ModelAsyncSelect from "@/components/ModelAsyncSelect";
import PageHeader from "@/components/PageHeader";
import { useDialogs } from "@/components/DialogProvider";
import PriceRequestCard, { PriceRequestProductStrip } from "@/components/price-calculation/PriceRequestCard";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { priceRequestSurface, type PriceCalculationRequest, type PriceRequestStatus } from "@/lib/priceCalculationRequests";
import { modelVariantPictureUrl } from "@/lib/modelVariants";
import { modelAutofillValues, type PriceCalculationModelDetail } from "../../finance/price-calculation/modelAutofill";

type SalesDraft = {
  id: string;
  modelId: number | null;
  modelNo: string;
  variantNo: string;
  modelName: string;
  sizes: string;
  modelImageUrl: string;
  variantImageUrl: string;
};

function emptyDraft(id: string): SalesDraft {
  return { id, modelId: null, modelNo: "", variantNo: "", modelName: "", sizes: "", modelImageUrl: "", variantImageUrl: "" };
}

function statusKey(status: PriceRequestStatus): string {
  if (status === "complete") return "page.priceWorkflow.statusComplete";
  if (status === "in_progress") return "page.priceWorkflow.statusPartial";
  return "page.priceWorkflow.statusNew";
}

export default function SalesPriceRequestsPage() {
  const { lang, t } = useT();
  const dialogs = useDialogs();
  const nextDraftId = useRef(2);
  const requestSequence = useRef(new Map<string, number>());
  const { data: requests, error, isLoading, mutate } = useSWR<PriceCalculationRequest[]>(
    "/api/price-calculation/requests",
    fetcher,
    { refreshInterval: 5_000 },
  );
  const [drafts, setDrafts] = useState<SalesDraft[]>([emptyDraft("sales-price-draft-1")]);
  const [savingId, setSavingId] = useState<string | null>(null);

  function addRow() {
    const id = `sales-price-draft-${nextDraftId.current}`;
    nextDraftId.current += 1;
    setDrafts((current) => [...current, emptyDraft(id)]);
  }

  async function selectModel(draftId: string, modelId: number) {
    const sequence = (requestSequence.current.get(draftId) || 0) + 1;
    requestSequence.current.set(draftId, sequence);
    setDrafts((current) => current.map((draft) => draft.id === draftId ? { ...draft, modelId } : draft));
    try {
      const model = await api.get<PriceCalculationModelDetail>(`/api/models/${modelId}`);
      if (requestSequence.current.get(draftId) !== sequence) return;
      const values = modelAutofillValues(model, lang);
      setDrafts((current) => current.map((draft) => draft.id === draftId ? {
        ...draft,
        modelId,
        modelNo: values.modelNo || "",
        variantNo: values.variantNo || "",
        modelName: values.modelName || "",
        sizes: values.modelSize || "",
        modelImageUrl: String(model.primary_image_url || model.primary_image?.file_url || ""),
        variantImageUrl: modelVariantPictureUrl(model),
      } : draft));
    } catch {
      if (requestSequence.current.get(draftId) !== sequence) return;
      setDrafts((current) => current.map((draft) => draft.id === draftId ? emptyDraft(draft.id) : draft));
      await dialogs.notify(t("page.priceCalculation.modelLoadError"));
    }
  }

  async function save(draft: SalesDraft) {
    if (!draft.modelId) {
      await dialogs.notify(t("page.priceWorkflow.selectVariantFirst"));
      return;
    }
    setSavingId(draft.id);
    try {
      await api.post("/api/price-calculation/requests", { model_id: draft.modelId });
      setDrafts((current) => current.filter((candidate) => candidate.id !== draft.id));
      await mutate();
    } catch (saveError) {
      await dialogs.notify(saveError instanceof Error ? saveError.message : t("page.priceWorkflow.saveError"));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="min-w-0">
      <PageHeader
        title={t("page.priceWorkflow.salesTitle")}
        subtitle={t("page.priceWorkflow.salesSubtitle")}
        actions={<button type="button" className="btn btn-primary" onClick={addRow}><Plus aria-hidden="true" />{t("page.priceCalculation.addRow")}</button>}
      />
      <div className="max-w-6xl space-y-2.5">
        {drafts.map((draft) => (
          <section key={draft.id} className={`rounded-lg border p-2.5 shadow-sm ${priceRequestSurface("new")}`}>
            <div className="mb-2 flex items-center justify-between gap-2 border-b border-black/10 pb-1.5">
              <div className="text-sm font-semibold">{t("page.priceWorkflow.newRequest")}</div>
              <button type="button" className="btn btn-primary h-8 px-3 text-xs" disabled={savingId === draft.id} onClick={() => save(draft)}>{savingId === draft.id ? t("page.priceWorkflow.saving") : t("page.priceWorkflow.save")}</button>
            </div>
            <PriceRequestProductStrip
              product={{
                modelNo: draft.modelNo,
                variantNo: draft.variantNo,
                modelName: draft.modelName,
                sizes: draft.sizes,
                kroyNo: "",
                modelImageUrl: draft.modelImageUrl,
                variantImageUrl: draft.variantImageUrl,
              }}
              labels={{
                model: t("page.priceCalculation.modelNo"),
                variant: t("page.priceCalculation.variantNo"),
                size: t("page.priceCalculation.modelSize"),
                kroy: t("page.priceCalculation.kroyNo"),
                modelPicture: t("page.priceWorkflow.modelPicture"),
                variantPicture: t("page.priceWorkflow.variantPicture"),
                openPicture: t("page.priceWorkflow.openPicture"),
                noPicture: t("page.priceWorkflow.noPicture"),
              }}
              showKroy={false}
              controls={{
                variant: <div className="min-w-0">
                  <label htmlFor={`${draft.id}-variant`} className="mb-0.5 block text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{t("page.priceCalculation.variantNo")}</label>
                  <ModelAsyncSelect inputId={`${draft.id}-variant`} value={draft.modelId} onChange={(modelId) => selectModel(draft.id, modelId)} placeholder={t("page.priceCalculation.searchVariant")} noResultsText={t("page.priceCalculation.noVariantMatches")} loadingText={t("common.loading")} loadMoreText={t("common.loadMore")} />
                </div>,
              }}
            />
          </section>
        ))}

        {isLoading ? <div className="text-sm text-[var(--erp-text-muted)]">{t("common.loading")}</div> : null}
        {error ? <div className="text-sm text-red-700">{t("page.priceWorkflow.loadError")}</div> : null}
        {(requests || []).map((request) => <PriceRequestCard
          key={request.id}
          request={request}
          status={request.overall_status}
          statusLabel={t(statusKey(request.overall_status))}
          labels={{
            request: t("page.priceWorkflow.request"),
            model: t("page.priceCalculation.modelNo"),
            variant: t("page.priceCalculation.variantNo"),
            size: t("page.priceCalculation.modelSize"),
            kroy: t("page.priceCalculation.kroyNo"),
            modelPicture: t("page.priceWorkflow.modelPicture"),
            variantPicture: t("page.priceWorkflow.variantPicture"),
            openPicture: t("page.priceWorkflow.openPicture"),
            noPicture: t("page.priceWorkflow.noPicture"),
          }}
        />)}
      </div>
    </div>
  );
}
