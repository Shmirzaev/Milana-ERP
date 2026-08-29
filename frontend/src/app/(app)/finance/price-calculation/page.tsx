"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import useSWR from "swr";
import ImageThumbnail from "@/components/ImageThumbnail";
import PageHeader from "@/components/PageHeader";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { priceRequestSurface, type PriceCalculationRequest, type PriceRequestStatus } from "@/lib/priceCalculationRequests";
import {
  PRICE_CALCULATION_DETAIL_GROUPS,
  PRICE_CALCULATION_SUMMARY_COLUMNS,
  type CalculatedValues,
  type EditableField,
  type PriceCalculationColumn,
  type PriceCalculationRow,
} from "./priceCalculation";

const LANGUAGE_LOCALES = { en: "en-US", ru: "ru-RU", uz: "uz-UZ" } as const;
const FINANCE_FIELDS = new Set<EditableField>(["costPriceUzs", "sellingPrice", "profitPercentage", "exchangeRate"]);

function text(value: number | string | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function rowFromRequest(request: PriceCalculationRequest): PriceCalculationRow {
  return {
    id: `price-request-${request.id}`,
    kroyNo: request.kroy_no || "",
    date: request.date?.slice(0, 10) || "",
    modelNo: request.model_no,
    variantNo: request.variant_no,
    modelCategory: request.model_category || "",
    modelName: request.model_name,
    modelSize: request.model_sizes.join(", "),
    fabricWidth: text(request.fabric_width_m),
    layupMeters: text(request.lay_length_m),
    sizeCount: text(request.size_count),
    gsm: text(request.gramage),
    bindingKgPerPiece: text(request.binding_kg_per_piece),
    fabricPrice: text(request.fabric_price),
    sewingCost: text(request.sewing_cost),
    packagingCost: text(request.packaging_cost),
    accessory1: text(request.accessories[0]?.price),
    accessory2: text(request.accessories[1]?.price),
    accessory3: text(request.accessories[2]?.price),
    accessory4: text(request.accessories[3]?.price),
    costPriceUzs: text(request.cost_price_uzs),
    sellingPrice: text(request.selling_price),
    profitPercentage: text(request.profit_percentage),
    exchangeRate: text(request.exchange_rate),
  };
}

function calculationsFromRequest(request: PriceCalculationRequest): CalculatedValues {
  return {
    fabricConsumption: request.fabric_consumption,
    consumptionCost: request.consumption_cost,
    bindingPrice: request.binding_price,
    costPrice: request.cost_price,
    difference: request.difference,
  };
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

function PriceCalculationField({ column, row, calculated, formatter, label, onChange, readOnly, compact = false }: {
  column: PriceCalculationColumn;
  row: PriceCalculationRow;
  calculated: CalculatedValues;
  formatter: Intl.NumberFormat;
  label: string;
  onChange: (field: EditableField, value: string) => void;
  readOnly: boolean;
  compact?: boolean;
}) {
  if (column.kind === "calculated") {
    return (
      <div className="min-w-0">
        <span className={`${compact ? "mb-0.5 text-[11px] leading-3.5" : "mb-1.5 text-xs leading-4"} block font-medium text-[var(--erp-text-muted)]`}>{label}</span>
        <output aria-label={label} className={`${compact ? "h-8 px-2 py-1.5" : "h-9 px-2.5 py-2"} block w-full rounded-md border border-[var(--erp-border)] bg-white/70 text-right text-sm font-medium tabular-nums text-[var(--erp-text)]`}>
          {calculated[column.field] === null ? "—" : formatter.format(calculated[column.field])}
        </output>
      </div>
    );
  }
  const locked = Boolean(column.readOnly || readOnly);
  return (
    <label className="min-w-0">
      <span className={`${compact ? "mb-0.5 text-[11px] leading-3.5" : "mb-1.5 text-xs leading-4"} block font-medium text-[var(--erp-text-muted)]`}>{label}</span>
      <input type={column.inputType} inputMode={column.inputType === "number" ? "decimal" : undefined} step={column.inputType === "number" ? "any" : undefined} value={row[column.field]} onChange={(event) => onChange(column.field, event.target.value)} readOnly={locked} aria-label={label} className={`${compact ? "h-8 px-2" : "h-9 px-2.5"} w-full min-w-0 rounded-md border border-[var(--erp-border-strong)] text-sm text-[var(--erp-text)] outline-none transition ${locked ? "cursor-default bg-white/70 tabular-nums" : "bg-white focus:border-[var(--erp-accent)] focus:ring-2 focus:ring-[color-mix(in_srgb,var(--erp-accent)_20%,transparent)]"}`} />
    </label>
  );
}

export default function PriceCalculationPage() {
  const { lang, t } = useT();
  const dialogs = useDialogs();
  const { data: requests, error, isLoading, mutate } = useSWR<PriceCalculationRequest[]>("/api/price-calculation/requests", fetcher, { refreshInterval: 5_000 });
  const [expandedRows, setExpandedRows] = useState<Set<string>>(() => new Set());
  const [editingRequests, setEditingRequests] = useState<Set<number>>(() => new Set());
  const [financeDrafts, setFinanceDrafts] = useState<Record<number, Partial<PriceCalculationRow>>>({});
  const [savingId, setSavingId] = useState<number | null>(null);
  const formatter = useMemo(() => new Intl.NumberFormat(LANGUAGE_LOCALES[lang], { maximumFractionDigits: 4 }), [lang]);

  function toggleDetails(rowId: string) {
    setExpandedRows((current) => {
      const next = new Set(current);
      if (next.has(rowId)) next.delete(rowId); else next.add(rowId);
      return next;
    });
  }

  function beginFinanceEdit(request: PriceCalculationRequest) {
    setFinanceDrafts((current) => ({ ...current, [request.id]: rowFromRequest(request) }));
    setEditingRequests((current) => new Set(current).add(request.id));
  }

  function updateFinanceDraft(requestId: number, field: EditableField, value: string) {
    if (!FINANCE_FIELDS.has(field)) return;
    setFinanceDrafts((current) => ({ ...current, [requestId]: { ...(current[requestId] || {}), [field]: value } }));
  }

  async function saveFinance(request: PriceCalculationRequest, row: PriceCalculationRow) {
    setSavingId(request.id);
    try {
      await api.patch(`/api/price-calculation/requests/${request.id}/finance`, {
        cost_price_uzs: optionalNumber(row.costPriceUzs),
        selling_price: optionalNumber(row.sellingPrice),
        profit_percentage: optionalNumber(row.profitPercentage),
        exchange_rate: optionalNumber(row.exchangeRate),
      });
      setEditingRequests((current) => {
        const next = new Set(current);
        next.delete(request.id);
        return next;
      });
      await mutate();
    } catch (saveError) {
      await dialogs.notify(saveError instanceof Error ? saveError.message : t("page.priceWorkflow.saveError"));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="min-w-0">
      <PageHeader title={t("page.priceCalculation.title")} subtitle={t("page.priceWorkflow.financeReceivedSubtitle")} />
      {isLoading ? <div className="mb-3 text-sm text-[var(--erp-text-muted)]">{t("common.loading")}</div> : null}
      {error ? <div className="mb-3 text-sm text-red-700">{t("page.priceWorkflow.loadError")}</div> : null}
      {!isLoading && !error && requests?.length === 0 ? <div className="text-sm text-[var(--erp-text-muted)]">{t("page.priceWorkflow.empty")}</div> : null}
      <div className="space-y-4">
        {(requests || []).map((request) => {
          const baseRow = rowFromRequest(request);
          const row = editingRequests.has(request.id) ? { ...baseRow, ...financeDrafts[request.id] } : baseRow;
          const detailsOpen = expandedRows.has(row.id);
          const calculated = calculationsFromRequest(request);
          const isEditing = editingRequests.has(request.id);
          const accessoryNames = request.accessories.map((accessory) => accessory.name || "");
          return (
            <section key={request.id} className={`overflow-hidden rounded-lg border shadow-sm ${priceRequestSurface(request.overall_status)}`}>
              <div className="flex min-h-9 items-center justify-between gap-2 border-b border-black/10 px-3 py-1.5">
                <div className="min-w-0 text-sm font-semibold leading-5 text-[var(--erp-text)]">{t("page.priceWorkflow.request")} #{request.id}<span className="ml-2 text-xs font-medium text-[var(--erp-text-soft)]">{t(statusKey(request.overall_status))}</span></div>
                <div className="flex shrink-0 gap-2">
                  <button type="button" className="btn h-8 px-2.5 text-xs" disabled={isEditing || savingId === request.id} onClick={() => beginFinanceEdit(request)}>{t("page.priceWorkflow.edit")}</button>
                  <button type="button" className="btn btn-primary h-8 px-2.5 text-xs" disabled={!isEditing || savingId === request.id} onClick={() => saveFinance(request, row)}>{savingId === request.id ? t("page.priceWorkflow.saving") : t("page.priceWorkflow.save")}</button>
                </div>
              </div>
              <div className="flex gap-2 border-b border-black/10 px-3 py-2">
                <div>
                  <div className="mb-0.5 text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{t("page.priceWorkflow.modelPicture")}</div>
                  <ImageThumbnail imageUrl={request.model_image_url} label={`${request.model_no} ${t("page.priceWorkflow.modelPicture")}`} title={`${t("page.priceWorkflow.openPicture")}: ${t("page.priceWorkflow.modelPicture")}`} emptyLabel={t("page.priceWorkflow.noPicture")} />
                </div>
                <div>
                  <div className="mb-0.5 text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{t("page.priceWorkflow.variantPicture")}</div>
                  <ImageThumbnail imageUrl={request.variant_image_url} label={`${request.variant_no} ${t("page.priceWorkflow.variantPicture")}`} title={`${t("page.priceWorkflow.openPicture")}: ${t("page.priceWorkflow.variantPicture")}`} emptyLabel={t("page.priceWorkflow.noPicture")} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-x-2 gap-y-1.5 px-3 py-2 md:grid-cols-4 xl:grid-cols-[repeat(6,minmax(0,1fr))_2rem] xl:items-end">
                {PRICE_CALCULATION_SUMMARY_COLUMNS.map((column) => {
                  const canEdit = isEditing && FINANCE_FIELDS.has(column.field as EditableField) && (column.field !== "sellingPrice" || request.cost_price !== null);
                  return <PriceCalculationField key={column.field} column={column} row={row} calculated={calculated} formatter={formatter} label={t(column.labelKey)} readOnly={!canEdit} onChange={(field, value) => updateFinanceDraft(request.id, field, value)} compact />;
                })}
                <button type="button" className="inline-flex h-8 w-8 self-end justify-self-end items-center justify-center rounded-md border border-[var(--erp-border-strong)] bg-white/60 text-[var(--erp-text-soft)] transition hover:bg-white hover:text-[var(--erp-text)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[color-mix(in_srgb,var(--erp-accent)_25%,transparent)]" onClick={() => toggleDetails(row.id)} aria-label={detailsOpen ? t("page.priceCalculation.hideDetails") : t("page.priceCalculation.showDetails")} aria-expanded={detailsOpen} aria-controls={`${row.id}-details`}>
                  {detailsOpen ? <ChevronUp className="h-4 w-4" aria-hidden="true" /> : <ChevronDown className="h-4 w-4" aria-hidden="true" />}
                </button>
              </div>
              {detailsOpen ? <div id={`${row.id}-details`} className="divide-y divide-black/10 border-t border-black/10">
                {PRICE_CALCULATION_DETAIL_GROUPS.map((group) => <div key={group.labelKey} className="px-4 py-3">
                  <h2 className="mb-2 text-sm font-semibold text-[var(--erp-text-strong)]">{t(group.labelKey)}</h2>
                  <div className={`grid gap-x-3 gap-y-3 ${group.gridClass}`}>
                    {group.columns.map((column) => {
                      const accessoryIndex = column.kind === "editable" && column.accessoryNumber ? column.accessoryNumber - 1 : -1;
                      const label = accessoryIndex >= 0 && accessoryNames[accessoryIndex] ? accessoryNames[accessoryIndex] : column.kind === "editable" && column.accessoryNumber ? `${t(column.labelKey)} ${column.accessoryNumber}` : t(column.labelKey);
                      const canEdit = isEditing && column.kind === "editable" && FINANCE_FIELDS.has(column.field) && (column.field !== "sellingPrice" || request.cost_price !== null);
                      return <PriceCalculationField key={column.field} column={column} row={row} calculated={calculated} formatter={formatter} label={label} readOnly={!canEdit} onChange={(field, value) => updateFinanceDraft(request.id, field, value)} />;
                    })}
                  </div>
                </div>)}
              </div> : null}
            </section>
          );
        })}
      </div>
    </div>
  );
}
