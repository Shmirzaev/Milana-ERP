"use client";

import { useState } from "react";
import PageHeader from "@/components/PageHeader";
import PriceRequestCard from "./PriceRequestCard";
import PriceRequestPagination from "./PriceRequestPagination";
import { usePriceRequests } from "@/hooks/usePriceRequests";
import { api } from "@/lib/api";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { numberInputValue, type PriceCalculationRequest } from "@/lib/priceCalculationRequests";
import { priceWorkflowMessages } from "@/lib/priceWorkflowMessages";

type Team = "purchasing" | "accessories";
type Draft = { revision: number; fabric: string; sewing: string; printing: string; accessories: { name: string; price: string }[]; noAccessories: boolean; reason: string };
const numeric = (value: string) => value.trim() ? Number(value) : null;
function draftOf(request: PriceCalculationRequest): Draft {
  const rates = [...new Set(request.materials.map(row => row.rate))];
  return { revision: request.revision, fabric: numberInputValue(rates.length === 1 ? rates[0] : null),
    sewing: numberInputValue(request.sewing_cost), printing: numberInputValue(request.printing_cost),
    accessories: request.accessories.length ? request.accessories.map(row => ({ name: row.name || "", price: numberInputValue(row.price) })) : [{ name: "", price: "" }],
    noAccessories: Boolean(request.no_accessories_reason), reason: request.no_accessories_reason || "" };
}

export default function DepartmentPriceQueue({ team }: { team: Team }) {
  const { lang, t } = useT();
  const m = priceWorkflowMessages(lang);
  const { me } = useMe();
  const [queue, setQueue] = useState<"pending" | "completed">("pending");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [catalog, setCatalog] = useState<"standard" | "usluga">("standard");
  const { data, error, isLoading, mutate, hasMore, isLoadingMore, loadMore } = usePriceRequests({ queue, team, q: search, catalog_scope: catalog });
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [errors, setErrors] = useState<Record<number, string>>({});
  const fmt = new Intl.NumberFormat(lang, { maximumFractionDigits: 6 });
  function update(id: number, changes: Partial<Draft>) { setDrafts(current => ({ ...current, [id]: { ...current[id], ...changes } })); }
  async function action(request: PriceCalculationRequest, submit: boolean) {
    setBusy(request.id); setErrors(current => ({ ...current, [request.id]: "" }));
    try {
      const draft = drafts[request.id];
      if (submit) {
        await api.post(`/api/price-calculation/requests/${request.id}/submit/${team}`, { expected_revision: request.revision });
      } else if (draft) {
        const payload = team === "purchasing" ? {
          expected_revision: draft.revision, sewing_cost: numeric(draft.sewing), printing_cost: numeric(draft.printing),
          fabric_price: numeric(draft.fabric),
        } : {
          expected_revision: draft.revision, no_accessories_reason: draft.noAccessories ? draft.reason : null,
          accessories: draft.noAccessories ? [] : draft.accessories.filter(row => row.name.trim() || row.price.trim()).map(row => ({ name: row.name, price: numeric(row.price) })),
        };
        await api.patch(`/api/price-calculation/requests/${request.id}/${team}`, payload);
      }
      setDrafts(current => { const next = { ...current }; delete next[request.id]; return next; });
      await mutate();
    } catch (err) { setErrors(current => ({ ...current, [request.id]: err instanceof Error ? err.message : m.error })); }
    finally { setBusy(null); }
  }
  return <div className="min-w-0">
    <PageHeader title={m[team]} subtitle={m.teamNote} />
    <div className="mb-4 flex flex-wrap items-end gap-3">
      <div className="flex gap-2">{(["pending", "completed"] as const).map(value => <button key={value} className={`btn ${queue === value ? "btn-primary" : ""}`} onClick={() => setQueue(value)}>{m[value]}</button>)}</div>
      <form className="flex gap-2" onSubmit={event => { event.preventDefault(); setSearch(query); }}><input className="input w-64" aria-label={m.search} placeholder={m.search} value={query} onChange={event => setQuery(event.target.value)} /><button className="btn">{m.apply}</button></form>
      {me?.factory_code === "ECO" && can(me, "usluga.view", "usluga.manage") ? <select className="input w-44" aria-label={m.standard} value={catalog} onChange={event => setCatalog(event.target.value as typeof catalog)}><option value="standard">{m.standard}</option><option value="usluga">{m.usluga}</option></select> : null}
    </div>
    {isLoading ? <p>{m.loading}</p> : null}{error ? <p className="text-red-700">{m.error}</p> : null}
    {!isLoading && !error && !data.length ? <p className="text-sm text-[var(--erp-text-muted)]">{m.empty}</p> : null}
    <div className="max-w-6xl space-y-3">{data.map(request => {
      const draft = drafts[request.id]; const row = draft || draftOf(request);
      const submitted = team === "purchasing" ? request.purchasing_submitted_at : request.accessories_submitted_at;
      const editable = !submitted && request.workflow_state === "collecting";
      return <PriceRequestCard key={request.id} request={request} status={submitted ? "complete" : "in_progress"} statusLabel={submitted ? m.submitted : m.waiting}
        labels={{ request: t("page.priceWorkflow.request"), model: m.model, variant: m.variant, size: t("page.priceCalculation.modelSize"), kroy: t("page.priceCalculation.kroyNo"), modelPicture: t("page.priceWorkflow.modelPicture"), variantPicture: t("page.priceWorkflow.variantPicture"), openPicture: t("page.priceWorkflow.openPicture"), noPicture: t("page.priceWorkflow.noPicture") }}>
        {request.correction_reason ? <p className="mb-3 text-sm text-amber-900">{m.correction}: {request.correction_reason}</p> : null}
        {team === "purchasing" ? <>
          <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr><th className="text-left">{m.material}</th><th className="text-right">{m.consumption}</th></tr></thead><tbody>{request.materials.map(material => <tr key={material.key} className="border-t border-[var(--erp-border)]"><td className="py-2">{material.name}</td><td className="py-2 text-right tabular-nums">{material.consumption === null ? m.quantityMissing : fmt.format(material.consumption)} {material.unit}</td></tr>)}</tbody></table></div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-sm">{m.fabricPrice}<input className="input mt-1" type="number" min="0" step="0.0001" disabled={!draft} value={row.fabric} onChange={event => update(request.id, { fabric: event.target.value })} /></label><label className="text-sm">{m.sewing}<input className="input mt-1" type="number" min="0" step="0.0001" disabled={!draft} value={row.sewing} onChange={event => update(request.id, { sewing: event.target.value })} /></label>{request.printing_required ? <label className="text-sm">{m.printing}<input className="input mt-1" type="number" min="0" step="0.0001" disabled={!draft} value={row.printing} onChange={event => update(request.id, { printing: event.target.value })} /></label> : null}</div>
          {request.calculation_issues.includes("passport_consumption") ? <p className="mt-2 text-sm text-amber-900">{m.missing} <a className="underline" href="/cutting-passports">{m.viewPassport}</a></p> : null}
        </> : <div className="space-y-3">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!draft} checked={row.noAccessories} onChange={event => update(request.id, { noAccessories: event.target.checked })} />{m.noAccessories}</label>
          {row.noAccessories ? <label className="block text-sm">{m.noAccessoriesReason}<input className="input mt-1" disabled={!draft} value={row.reason} onChange={event => update(request.id, { reason: event.target.value })} /></label> : <>{row.accessories.map((accessory, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_10rem_auto]"><label className="text-sm">{m.accessoryName}<input className="input mt-1" disabled={!draft} value={accessory.name} onChange={event => update(request.id, { accessories: row.accessories.map((value, i) => i === index ? { ...value, name: event.target.value } : value) })} /></label><label className="text-sm">{m.accessoryPrice}<input className="input mt-1" type="number" min="0" step="0.0001" disabled={!draft} value={accessory.price} onChange={event => update(request.id, { accessories: row.accessories.map((value, i) => i === index ? { ...value, price: event.target.value } : value) })} /></label><button className="btn self-end" disabled={!draft || row.accessories.length === 1} onClick={() => update(request.id, { accessories: row.accessories.filter((_, i) => i !== index) })}>{m.remove}</button></div>)}{draft && row.accessories.length < 4 ? <button className="btn" onClick={() => update(request.id, { accessories: [...row.accessories, { name: "", price: "" }] })}>{m.add}</button> : null}</>}
        </div>}
        {editable ? <div className="mt-3 flex flex-wrap justify-end gap-2"><button className="btn" disabled={Boolean(draft) || busy === request.id} onClick={() => setDrafts(current => ({ ...current, [request.id]: draftOf(request) }))}>{t("page.priceWorkflow.edit")}</button><button className="btn" disabled={!draft || busy === request.id} onClick={() => action(request, false)}>{m.draft}</button><button className="btn btn-primary" disabled={Boolean(draft) || busy === request.id} onClick={() => action(request, true)}>{busy === request.id ? m.saving : m.submit}</button></div> : null}
        {errors[request.id] ? <p role="alert" className="mt-2 text-sm text-red-700">{errors[request.id]}</p> : null}
      </PriceRequestCard>;
    })}</div>
    <PriceRequestPagination hasMore={hasMore} isLoadingMore={isLoadingMore} loadMore={loadMore} />
  </div>;
}
