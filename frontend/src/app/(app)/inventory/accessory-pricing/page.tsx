"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import PriceRequestCard from "@/components/price-calculation/PriceRequestCard";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import {
  numberInputValue,
  type PriceCalculationRequest,
  type PriceRequestAccessory,
  type PriceRequestStatus,
} from "@/lib/priceCalculationRequests";

type AccessoryDraft = { name: string; price: string };

function requestDraft(request: PriceCalculationRequest): AccessoryDraft[] {
  const rows = request.accessories.map((row) => ({
    name: row.name || "",
    price: numberInputValue(row.price),
  }));
  return rows.length ? rows : [{ name: "", price: "" }];
}

function statusKey(status: PriceRequestStatus): string {
  if (status === "complete") return "page.priceWorkflow.statusComplete";
  if (status === "in_progress") return "page.priceWorkflow.statusPartial";
  return "page.priceWorkflow.statusNew";
}

function optionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function AccessoryPricingPage() {
  const { t } = useT();
  const { data, error, isLoading, mutate } = useSWR<PriceCalculationRequest[]>(
    "/api/price-calculation/requests",
    fetcher,
    { refreshInterval: 5_000 },
  );
  const [drafts, setDrafts] = useState<Record<number, AccessoryDraft[]>>({});
  const [editing, setEditing] = useState<Set<number>>(() => new Set());
  const [savingId, setSavingId] = useState<number | null>(null);
  const [saveErrors, setSaveErrors] = useState<Record<number, string>>({});

  function beginEdit(request: PriceCalculationRequest) {
    setDrafts((current) => ({ ...current, [request.id]: requestDraft(request) }));
    setSaveErrors((current) => ({ ...current, [request.id]: "" }));
    setEditing((current) => new Set(current).add(request.id));
  }

  function updateRow(request: PriceCalculationRequest, index: number, field: keyof AccessoryDraft, value: string) {
    setDrafts((current) => {
      const rows = [...(current[request.id] || requestDraft(request))];
      rows[index] = { ...rows[index], [field]: value };
      return { ...current, [request.id]: rows };
    });
  }

  function addRow(request: PriceCalculationRequest) {
    setDrafts((current) => ({
      ...current,
      [request.id]: [...(current[request.id] || requestDraft(request)), { name: "", price: "" }].slice(0, 4),
    }));
  }

  function removeRow(request: PriceCalculationRequest, index: number) {
    setDrafts((current) => {
      const rows = (current[request.id] || requestDraft(request)).filter((_, rowIndex) => rowIndex !== index);
      return { ...current, [request.id]: rows.length ? rows : [{ name: "", price: "" }] };
    });
  }

  async function save(request: PriceCalculationRequest) {
    const rows = drafts[request.id] || requestDraft(request);
    const accessories: PriceRequestAccessory[] = rows.map((row) => ({
      name: row.name.trim() || null,
      price: optionalNumber(row.price),
    }));
    setSavingId(request.id);
    setSaveErrors((current) => ({ ...current, [request.id]: "" }));
    try {
      await api.patch(`/api/price-calculation/requests/${request.id}/accessories`, { accessories });
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
      <PageHeader title={t("page.priceWorkflow.accessoryTitle")} subtitle={t("page.priceWorkflow.accessorySubtitle")} />
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
          const rows = drafts[request.id] || requestDraft(request);
          return (
            <PriceRequestCard
              key={request.id}
              request={request}
              status={request.accessories_status}
              statusLabel={t(statusKey(request.accessories_status))}
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
              <div className="space-y-1.5">
                {rows.map((row, index) => (
                  <div key={index} className="grid grid-cols-1 items-end gap-2 sm:grid-cols-[minmax(12rem,1.5fr)_minmax(9rem,1fr)_2.25rem]">
                    <label className="block min-w-0">
                      <span className="mb-0.5 block text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{t("page.priceWorkflow.accessoryName")}</span>
                      <input value={row.name} disabled={!isEditing} onChange={(event) => updateRow(request, index, "name", event.target.value)} className="h-9 w-full rounded-md border border-[var(--erp-border-strong)] bg-white px-2.5 text-sm outline-none focus:border-[var(--erp-accent)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--erp-accent)_20%,transparent)] disabled:cursor-default disabled:bg-white/70" />
                    </label>
                    <label className="block min-w-0">
                      <span className="mb-0.5 block text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{t("page.priceWorkflow.accessoryPrice")}</span>
                      <input type="number" inputMode="decimal" step="any" value={row.price} disabled={!isEditing} onChange={(event) => updateRow(request, index, "price", event.target.value)} className="h-9 w-full rounded-md border border-[var(--erp-border-strong)] bg-white px-2.5 text-sm outline-none focus:border-[var(--erp-accent)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--erp-accent)_20%,transparent)] disabled:cursor-default disabled:bg-white/70" />
                    </label>
                    <button type="button" className="icon-btn h-9 w-9" disabled={!isEditing || rows.length === 1} onClick={() => removeRow(request, index)} aria-label={t("page.priceWorkflow.removeAccessory")}>
                      <Trash2 className="h-4 w-4" aria-hidden="true" />
                    </button>
                  </div>
                ))}
              </div>
              <div className="mt-1.5 flex flex-wrap justify-end gap-2">
                <button type="button" className="btn h-9 px-3" disabled={isEditing || savingId === request.id} onClick={() => beginEdit(request)}>{t("page.priceWorkflow.edit")}</button>
                <button type="button" className="btn btn-primary h-9 px-3" disabled={!isEditing || savingId === request.id} onClick={() => save(request)}>
                  {savingId === request.id ? t("page.priceWorkflow.saving") : t("page.priceWorkflow.save")}
                </button>
                {isEditing && rows.length < 4 ? (
                  <button type="button" className="btn h-9 px-3" onClick={() => addRow(request)}>
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                    {t("page.priceWorkflow.addAccessory")}
                  </button>
                ) : null}
              </div>
              {saveErrors[request.id] ? <p className="mt-1.5 text-xs text-red-700">{saveErrors[request.id]}</p> : null}
            </PriceRequestCard>
          );
        })}
      </div>
    </div>
  );
}
