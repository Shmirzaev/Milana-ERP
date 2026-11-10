"use client";

import { useState } from "react";
import PageHeader from "@/components/PageHeader";
import PriceRequestCard from "@/components/price-calculation/PriceRequestCard";
import PriceRequestPagination from "@/components/price-calculation/PriceRequestPagination";
import PriceCostDetails from "@/components/price-calculation/PriceCostDetails";
import VariantPriceRegister from "@/components/price-calculation/VariantPriceRegister";
import { usePriceRequests } from "@/hooks/usePriceRequests";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { numberInputValue, type PriceCalculationRequest } from "@/lib/priceCalculationRequests";
import { priceWorkflowMessages } from "@/lib/priceWorkflowMessages";

type Draft = { revision: number; selling: string; exchange: string };
export default function PriceCalculationPage() {
  const { lang, t } = useT(); const m = priceWorkflowMessages(lang); const { me } = useMe();
  const [view, setView] = useState<"pending" | "approval" | "report">("pending");
  const [query, setQuery] = useState(""); const [search, setSearch] = useState("");
  const [catalog, setCatalog] = useState<"standard" | "usluga">("standard");
  const { data, error, isLoading, mutate, hasMore, isLoadingMore, loadMore } = usePriceRequests({ queue: view === "approval" ? "approval" : "pending", q: search, catalog_scope: catalog });
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [corrections, setCorrections] = useState<Record<number, { revision: number; team: "purchasing" | "accessories" | "cutting" | "cancel"; reason: string }>>({});
  const [busy, setBusy] = useState<number | null>(null); const [errors, setErrors] = useState<Record<number, string>>({});
  async function action(request: PriceCalculationRequest, action: "draft" | "approve" | "return") {
    setBusy(request.id); setErrors(current => ({ ...current, [request.id]: "" }));
    try {
      const draft = drafts[request.id]; const correction = corrections[request.id];
      if (action === "draft" && draft) await api.patch(`/api/price-calculation/requests/${request.id}/finance`, { expected_revision: draft.revision, selling_price: draft.selling.trim() ? Number(draft.selling) : null, exchange_rate: draft.exchange.trim() ? Number(draft.exchange) : null });
      if (action === "approve") await api.post(`/api/price-calculation/requests/${request.id}/approve`, { expected_revision: draft?.revision ?? request.revision, selling_price: Number(draft?.selling ?? request.selling_price) });
      if (action === "return" && correction) await api.post(`/api/price-calculation/requests/${request.id}/${correction.team === "cancel" ? "cancel" : "return"}`, correction.team === "cancel" ? { expected_revision: correction.revision, reason: correction.reason } : { expected_revision: correction.revision, team: correction.team, reason: correction.reason });
      setDrafts(current => { const next = { ...current }; delete next[request.id]; return next; });
      setCorrections(current => { const next = { ...current }; delete next[request.id]; return next; });
      await mutate();
    } catch (err) { setErrors(current => ({ ...current, [request.id]: err instanceof Error ? err.message : m.error })); }
    finally { setBusy(null); }
  }
  return <div className="min-w-0">
    <PageHeader title={m.title} subtitle={m.financeNote} />
    <nav aria-label={m.title} className="mb-4 flex flex-wrap gap-2">{(["pending", "approval", "report"] as const).map(value => <button className={`btn ${view === value ? "btn-primary" : ""}`} key={value} onClick={() => setView(value)}>{m[value]}</button>)}</nav>
    <form className="mb-4 flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); setSearch(query); }}><input className="input w-72" aria-label={m.search} placeholder={m.search} value={query} onChange={event => setQuery(event.target.value)} /><button className="btn">{m.apply}</button>{me?.factory_code === "ECO" && can(me, "usluga.view", "usluga.manage") ? <select className="input w-44" aria-label={m.standard} value={catalog} onChange={event => setCatalog(event.target.value as typeof catalog)}><option value="standard">{m.standard}</option><option value="usluga">{m.usluga}</option></select> : null}</form>
    {view === "report" ? <VariantPriceRegister q={search} catalog={catalog} /> : <>
      {isLoading ? <p>{m.loading}</p> : null}{error ? <p role="alert" className="text-red-700">{m.error}</p> : null}{!isLoading && !error && !data.length ? <p className="text-sm">{m.empty}</p> : null}
      <div className="max-w-6xl space-y-4">{data.map(request => {
        const draft = drafts[request.id]; const correction = corrections[request.id];
        const row = draft || { revision: request.revision, selling: numberInputValue(request.selling_price), exchange: numberInputValue(request.exchange_rate) };
        return <PriceRequestCard key={request.id} request={request} status="in_progress" statusLabel={m[request.workflow_state]}
          labels={{ request: t("page.priceWorkflow.request"), model: m.model, variant: m.variant, size: t("page.priceCalculation.modelSize"), kroy: t("page.priceCalculation.kroyNo"), modelPicture: t("page.priceWorkflow.modelPicture"), variantPicture: t("page.priceWorkflow.variantPicture"), openPicture: t("page.priceWorkflow.openPicture"), noPicture: t("page.priceWorkflow.noPicture") }}>
          <div className="mb-3 flex flex-wrap gap-4 text-sm"><span>{m.purchasing}: {request.purchasing_submitted_at ? m.submitted : m.waiting}</span><span>{m.accessories}: {request.accessories_submitted_at ? m.submitted : m.waiting}</span><span>{m.owner}: {request.factory_code}</span></div>
          {request.correction_reason ? <p className="mb-3 text-sm text-amber-900">{m.correction}: {request.correction_reason}</p> : null}
          {request.calculation_issues.includes("passport_consumption") ? <p className="mb-3 text-sm text-amber-900">{m.missing}</p> : null}
          <details className="mb-4"><summary className="cursor-pointer text-sm font-medium">{m.netCost}: {request.cost_price === null ? "—" : new Intl.NumberFormat(lang, { maximumFractionDigits: 4 }).format(request.cost_price)}</summary><PriceCostDetails request={request} /></details>
          <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">{m.selling}<input className="input mt-1" type="number" min="0.0001" step="0.0001" disabled={!draft} value={row.selling} onChange={event => setDrafts(current => ({ ...current, [request.id]: { ...row, selling: event.target.value } }))} /></label><label className="text-sm">{m.exchange}<input className="input mt-1" type="number" min="0" step="0.0001" disabled={!draft} value={row.exchange} onChange={event => setDrafts(current => ({ ...current, [request.id]: { ...row, exchange: event.target.value } }))} /></label></div>
          <div className="mt-3 flex flex-wrap justify-end gap-2"><button className="btn" disabled={Boolean(draft) || busy === request.id} onClick={() => setDrafts(current => ({ ...current, [request.id]: row }))}>{t("page.priceWorkflow.edit")}</button><button className="btn" disabled={!draft || busy === request.id} onClick={() => action(request, "draft")}>{m.draft}</button>{request.can_approve ? <><button className="btn" disabled={busy === request.id} onClick={() => setCorrections(current => ({ ...current, [request.id]: { revision: request.revision, team: "purchasing", reason: "" } }))}>{m.return}</button><button className="btn" disabled={busy === request.id} onClick={() => setCorrections(current => ({ ...current, [request.id]: { revision: request.revision, team: "cancel", reason: "" } }))}>{m.cancelRequest}</button><button className="btn btn-primary" disabled={Boolean(draft) || request.workflow_state !== "awaiting_finance" || !request.selling_price || busy === request.id} onClick={() => action(request, "approve")}>{busy === request.id ? m.saving : m.confirm}</button></> : null}</div>
          {correction ? <div className="mt-3 flex flex-wrap gap-2 border-t border-[var(--erp-border)] pt-3"><select className="input w-44" aria-label={m.return} value={correction.team} onChange={event => setCorrections(current => ({ ...current, [request.id]: { ...correction, team: event.target.value as typeof correction.team } }))}>{(["purchasing", "accessories", "cutting", "cancel"] as const).map(team => <option value={team} key={team}>{team === "cancel" ? m.cancelRequest : m[team]}</option>)}</select><input className="input min-w-48 flex-1" aria-label={m.reason} placeholder={m.reason} value={correction.reason} onChange={event => setCorrections(current => ({ ...current, [request.id]: { ...correction, reason: event.target.value } }))} /><button className="btn" disabled={correction.reason.trim().length < 3 || busy === request.id} onClick={() => action(request, "return")}>{correction.team === "cancel" ? m.cancelRequest : m.return}</button><button className="btn" onClick={() => setCorrections(current => { const next = { ...current }; delete next[request.id]; return next; })}>{m.close}</button></div> : null}
          {errors[request.id] ? <p role="alert" className="mt-2 text-sm text-red-700">{errors[request.id]}</p> : null}
        </PriceRequestCard>;
      })}</div><PriceRequestPagination hasMore={hasMore} isLoadingMore={isLoadingMore} loadMore={loadMore} />
    </>}
  </div>;
}
