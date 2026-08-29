"use client";

import { useState } from "react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import PriceRequestCard from "@/components/price-calculation/PriceRequestCard";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { numberInputValue, type PriceCalculationRequest, type PriceRequestStatus } from "@/lib/priceCalculationRequests";

type CuttingDraft = {
  kroy_no: string;
  fabric_width_m: string;
  lay_length_m: string;
  size_count: string;
  gramage: string;
  binding_kg_per_piece: string;
};

type PassportLookup = {
  passport_no: string;
  fabric_width_m: number | null;
  lay_length_m: number | null;
  size_count: number | null;
  gramage: number | null;
  beka_per_piece_kg: number | null;
  other_beka_per_piece_kg: number | null;
};

function requestDraft(request: PriceCalculationRequest): CuttingDraft {
  return {
    kroy_no: request.kroy_no || "",
    fabric_width_m: numberInputValue(request.fabric_width_m),
    lay_length_m: numberInputValue(request.lay_length_m),
    size_count: numberInputValue(request.size_count),
    gramage: numberInputValue(request.gramage),
    binding_kg_per_piece: numberInputValue(request.binding_kg_per_piece),
  };
}

function optionalNumber(value: string): number | null {
  const parsed = Number(value.trim());
  return value.trim() && Number.isFinite(parsed) ? parsed : null;
}

function statusKey(status: PriceRequestStatus): string {
  if (status === "complete") return "page.priceWorkflow.statusComplete";
  if (status === "in_progress") return "page.priceWorkflow.statusPartial";
  return "page.priceWorkflow.statusNew";
}

function FormField({ label, value, disabled, text = false, integer = false, onChange, onBlur }: {
  label: string;
  value: string;
  disabled: boolean;
  text?: boolean;
  integer?: boolean;
  onChange: (value: string) => void;
  onBlur?: () => void;
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-0.5 block truncate text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{label}</span>
      <input
        type={text ? "text" : "number"}
        inputMode={text ? undefined : integer ? "numeric" : "decimal"}
        min={integer ? 1 : undefined}
        step={integer ? 1 : "any"}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        className="h-8 w-full rounded-md border border-[var(--erp-border-strong)] bg-white px-2 text-sm text-[var(--erp-text)] outline-none transition focus:border-[var(--erp-accent)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--erp-accent)_20%,transparent)] disabled:cursor-default disabled:bg-white/70"
      />
    </label>
  );
}

export default function CuttingPriceCalculationPage() {
  const { t } = useT();
  const { data, error, isLoading, mutate } = useSWR<PriceCalculationRequest[]>("/api/price-calculation/requests", fetcher, { refreshInterval: 5_000 });
  const [drafts, setDrafts] = useState<Record<number, CuttingDraft>>({});
  const [editing, setEditing] = useState<Set<number>>(() => new Set());
  const [savingId, setSavingId] = useState<number | null>(null);
  const [lookupState, setLookupState] = useState<Record<number, "found" | "manual" | "">>({});
  const [saveErrors, setSaveErrors] = useState<Record<number, string>>({});

  function beginEdit(request: PriceCalculationRequest) {
    setDrafts((current) => ({ ...current, [request.id]: requestDraft(request) }));
    setLookupState((current) => ({ ...current, [request.id]: "" }));
    setSaveErrors((current) => ({ ...current, [request.id]: "" }));
    setEditing((current) => new Set(current).add(request.id));
  }

  function updateDraft(request: PriceCalculationRequest, field: keyof CuttingDraft, value: string) {
    setDrafts((current) => {
      const draft = current[request.id] || requestDraft(request);
      if (field !== "kroy_no") return { ...current, [request.id]: { ...draft, [field]: value } };
      return {
        ...current,
        [request.id]: {
          ...draft,
          kroy_no: value,
          fabric_width_m: "",
          lay_length_m: "",
          size_count: "",
          gramage: "",
          binding_kg_per_piece: "",
        },
      };
    });
    if (field === "kroy_no") setLookupState((current) => ({ ...current, [request.id]: "" }));
  }

  async function autofillPassport(request: PriceCalculationRequest) {
    const draft = drafts[request.id] || requestDraft(request);
    const kroyNo = draft.kroy_no.trim();
    if (!kroyNo) return;
    try {
      const matches = await api.get<PassportLookup[]>(`/api/cutting-passports?q=${encodeURIComponent(kroyNo)}&limit=20`);
      const passport = matches.find((row) => row.passport_no.trim().toLocaleLowerCase() === kroyNo.toLocaleLowerCase());
      if (!passport) {
        setLookupState((current) => ({ ...current, [request.id]: "manual" }));
        return;
      }
      const hasBinding = passport.beka_per_piece_kg !== null || passport.other_beka_per_piece_kg !== null;
      const binding = (passport.beka_per_piece_kg || 0) + (passport.other_beka_per_piece_kg || 0);
      setDrafts((current) => ({
        ...current,
        [request.id]: {
          ...(current[request.id] || draft),
          fabric_width_m: numberInputValue(passport.fabric_width_m),
          lay_length_m: numberInputValue(passport.lay_length_m),
          size_count: numberInputValue(passport.size_count),
          gramage: numberInputValue(passport.gramage),
          binding_kg_per_piece: hasBinding ? numberInputValue(binding) : "",
        },
      }));
      setLookupState((current) => ({ ...current, [request.id]: "found" }));
    } catch {
      setLookupState((current) => ({ ...current, [request.id]: "manual" }));
    }
  }

  async function save(request: PriceCalculationRequest) {
    const draft = drafts[request.id] || requestDraft(request);
    if (!draft.kroy_no.trim()) {
      setSaveErrors((current) => ({ ...current, [request.id]: t("page.priceWorkflow.kroyRequired") }));
      return;
    }
    setSavingId(request.id);
    setSaveErrors((current) => ({ ...current, [request.id]: "" }));
    try {
      await api.patch(`/api/price-calculation/requests/${request.id}/cutting`, {
        kroy_no: draft.kroy_no.trim(),
        fabric_width_m: optionalNumber(draft.fabric_width_m),
        lay_length_m: optionalNumber(draft.lay_length_m),
        size_count: optionalNumber(draft.size_count),
        gramage: optionalNumber(draft.gramage),
        binding_kg_per_piece: optionalNumber(draft.binding_kg_per_piece),
      });
      setEditing((current) => {
        const next = new Set(current);
        next.delete(request.id);
        return next;
      });
      await mutate();
    } catch (saveError) {
      setSaveErrors((current) => ({ ...current, [request.id]: saveError instanceof Error ? saveError.message : t("page.priceWorkflow.saveError") }));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="min-w-0">
      <PageHeader title={t("page.priceWorkflow.cuttingTitle")} subtitle={t("page.priceWorkflow.cuttingSubtitle")} />
      <div className="w-full max-w-7xl space-y-2.5">
        {isLoading ? <div className="text-sm text-[var(--erp-text-muted)]">{t("common.loading")}</div> : null}
        {error ? <div className="text-sm text-red-700">{t("page.priceWorkflow.loadError")}</div> : null}
        {!isLoading && !error && data?.length === 0 ? <div className="rounded-lg border border-dashed border-[var(--erp-border-strong)] p-5 text-sm text-[var(--erp-text-muted)]">{t("page.priceWorkflow.empty")}</div> : null}
        {(data || []).map((request) => {
          const isEditing = editing.has(request.id);
          const draft = drafts[request.id] || requestDraft(request);
          return (
            <PriceRequestCard
              key={request.id}
              request={request}
              status={request.cutting_status}
              statusLabel={t(statusKey(request.cutting_status))}
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
              <div className="grid grid-cols-2 items-end gap-2 md:grid-cols-3 xl:grid-cols-[1fr_1fr_1fr_0.8fr_1fr_1.2fr_auto]">
                <FormField label={t("page.priceCalculation.kroyNo")} value={draft.kroy_no} disabled={!isEditing} text onChange={(value) => updateDraft(request, "kroy_no", value)} onBlur={() => autofillPassport(request)} />
                <FormField label={t("page.priceCalculation.fabricWidth")} value={draft.fabric_width_m} disabled={!isEditing} onChange={(value) => updateDraft(request, "fabric_width_m", value)} />
                <FormField label={t("page.priceCalculation.layupMeters")} value={draft.lay_length_m} disabled={!isEditing} onChange={(value) => updateDraft(request, "lay_length_m", value)} />
                <FormField label={t("page.priceCalculation.size")} value={draft.size_count} disabled={!isEditing} integer onChange={(value) => updateDraft(request, "size_count", value)} />
                <FormField label={t("page.priceCalculation.gsm")} value={draft.gramage} disabled={!isEditing} onChange={(value) => updateDraft(request, "gramage", value)} />
                <FormField label={t("page.priceCalculation.bindingKgPerPiece")} value={draft.binding_kg_per_piece} disabled={!isEditing} onChange={(value) => updateDraft(request, "binding_kg_per_piece", value)} />
                <div className="flex justify-end gap-2">
                  <button type="button" className="btn h-8 px-3 text-xs" disabled={isEditing || savingId === request.id} onClick={() => beginEdit(request)}>{t("page.priceWorkflow.edit")}</button>
                  <button type="button" className="btn btn-primary h-8 px-3 text-xs" disabled={!isEditing || savingId === request.id} onClick={() => save(request)}>{savingId === request.id ? t("page.priceWorkflow.saving") : t("page.priceWorkflow.save")}</button>
                </div>
              </div>
              {lookupState[request.id] ? <p className="mt-1.5 text-xs text-[var(--erp-text-soft)]">{t(lookupState[request.id] === "found" ? "page.priceWorkflow.passportFound" : "page.priceWorkflow.passportManual")}</p> : null}
              {saveErrors[request.id] ? <p className="mt-1.5 text-xs text-red-700">{saveErrors[request.id]}</p> : null}
            </PriceRequestCard>
          );
        })}
      </div>
    </div>
  );
}
