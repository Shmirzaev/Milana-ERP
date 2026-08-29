"use client";

import { useState } from "react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import PriceRequestCard from "@/components/price-calculation/PriceRequestCard";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import {
  numberInputValue,
  type PriceCalculationRequest,
  type PriceRequestStatus,
} from "@/lib/priceCalculationRequests";

type PurchasingDraft = { fabric_price: string; sewing_cost: string };

function requestDraft(request: PriceCalculationRequest): PurchasingDraft {
  return {
    fabric_price: numberInputValue(request.fabric_price),
    sewing_cost: numberInputValue(request.sewing_cost),
  };
}

function optionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function statusKey(status: PriceRequestStatus): string {
  if (status === "complete") return "page.priceWorkflow.statusComplete";
  if (status === "in_progress") return "page.priceWorkflow.statusPartial";
  return "page.priceWorkflow.statusNew";
}

function FormField({ label, value, type = "text", disabled, onChange }: {
  label: string;
  value: string;
  type?: "text" | "number";
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-0.5 block text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{label}</span>
      <input
        type={type}
        inputMode={type === "number" ? "decimal" : undefined}
        step={type === "number" ? "any" : undefined}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-md border border-[var(--erp-border-strong)] bg-white px-2.5 text-sm text-[var(--erp-text)] outline-none transition focus:border-[var(--erp-accent)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--erp-accent)_20%,transparent)] disabled:cursor-default disabled:bg-white/70"
      />
    </label>
  );
}

export default function PurchasingPriceCalculationPage() {
  const { t } = useT();
  const { data, error, isLoading, mutate } = useSWR<PriceCalculationRequest[]>(
    "/api/price-calculation/requests",
    fetcher,
    { refreshInterval: 5_000 },
  );
  const [drafts, setDrafts] = useState<Record<number, PurchasingDraft>>({});
  const [editing, setEditing] = useState<Set<number>>(() => new Set());
  const [savingId, setSavingId] = useState<number | null>(null);
  const [saveErrors, setSaveErrors] = useState<Record<number, string>>({});

  function beginEdit(request: PriceCalculationRequest) {
    setDrafts((current) => ({ ...current, [request.id]: requestDraft(request) }));
    setSaveErrors((current) => ({ ...current, [request.id]: "" }));
    setEditing((current) => new Set(current).add(request.id));
  }

  function updateDraft(request: PriceCalculationRequest, field: keyof PurchasingDraft, value: string) {
    setDrafts((current) => ({
      ...current,
      [request.id]: { ...(current[request.id] || requestDraft(request)), [field]: value },
    }));
  }

  async function save(request: PriceCalculationRequest) {
    const draft = drafts[request.id] || requestDraft(request);
    setSavingId(request.id);
    setSaveErrors((current) => ({ ...current, [request.id]: "" }));
    try {
      await api.patch(`/api/price-calculation/requests/${request.id}/purchasing`, {
        fabric_price: optionalNumber(draft.fabric_price),
        sewing_cost: optionalNumber(draft.sewing_cost),
      });
      setEditing((current) => {
        const next = new Set(current);
        next.delete(request.id);
        return next;
      });
      await mutate();
    } catch (saveError) {
      setSaveErrors((current) => ({
        ...current,
        [request.id]: saveError instanceof Error ? saveError.message : t("page.priceWorkflow.saveError"),
      }));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="min-w-0">
      <PageHeader title={t("page.priceWorkflow.purchasingTitle")} subtitle={t("page.priceWorkflow.purchasingSubtitle")} />
      <div className="w-full max-w-6xl space-y-2.5">
        {isLoading ? <div className="text-sm text-[var(--erp-text-muted)]">{t("common.loading")}</div> : null}
        {error ? <div className="text-sm text-red-700">{t("page.priceWorkflow.loadError")}</div> : null}
        {!isLoading && !error && data?.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[var(--erp-border-strong)] p-5 text-sm text-[var(--erp-text-muted)]">
            {t("page.priceWorkflow.empty")}
          </div>
        ) : null}
        {(data || []).map((request) => {
          const isEditing = editing.has(request.id);
          const draft = drafts[request.id] || requestDraft(request);
          return (
            <PriceRequestCard
              key={request.id}
              request={request}
              status={request.purchasing_status}
              statusLabel={t(statusKey(request.purchasing_status))}
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
            >
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
                <FormField label={t("page.priceCalculation.fabricPrice")} value={draft.fabric_price} type="number" disabled={!isEditing} onChange={(value) => updateDraft(request, "fabric_price", value)} />
                <FormField label={t("page.priceCalculation.sewingCost")} value={draft.sewing_cost} type="number" disabled={!isEditing} onChange={(value) => updateDraft(request, "sewing_cost", value)} />
                <div className="flex justify-end gap-2">
                  <button type="button" className="btn h-9 px-3" disabled={isEditing || savingId === request.id} onClick={() => beginEdit(request)}>{t("page.priceWorkflow.edit")}</button>
                  <button type="button" className="btn btn-primary h-9 px-3" disabled={!isEditing || savingId === request.id} onClick={() => save(request)}>
                    {savingId === request.id ? t("page.priceWorkflow.saving") : t("page.priceWorkflow.save")}
                  </button>
                </div>
              </div>
              {saveErrors[request.id] ? <p className="mt-1.5 text-xs text-red-700">{saveErrors[request.id]}</p> : null}
            </PriceRequestCard>
          );
        })}
      </div>
    </div>
  );
}
