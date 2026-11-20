"use client";

import { useDeferredValue, useState, type FormEvent } from "react";
import { Download } from "lucide-react";
import useSWR, { useSWRConfig } from "swr";
import SearchableSelect from "@/components/SearchableSelect";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { cuttingHandoffText, handoffFactoryName, type HandoffFactory } from "@/lib/cuttingHandoff";
import { useT } from "@/lib/i18n";
import { formatOrderReference } from "@/lib/orderRef";
import { shipmentReportDates } from "@/lib/shipmentReportDates";

type DispatchOption = { id: number; order_no: string; nastil: string; pieces: number };
type Dispatch = {
  order_no: string; production_no: string; nastil: string | null; factory: HandoffFactory;
  pieces: number; received_pieces: number; first_sent_at: string; last_received_at: string | null;
};

function DispatchTable({ rows, pending }: { rows: Dispatch[]; pending: boolean }) {
  const { lang } = useT();
  const copy = cuttingHandoffText[lang];
  if (!rows.length) return <p className="mt-2 text-sm text-slate-500">{pending ? copy.emptyPending : copy.emptyDaily}</p>;
  return <div className="mt-2 overflow-x-auto">
    <table className="table">
      <thead><tr><th>{copy.order}</th><th>{copy.nastil}</th><th>{copy.destination}</th>
        <th>{pending ? copy.pieces : copy.sent}</th>{!pending && <><th>{copy.accepted}</th><th>{copy.inTransit}</th></>}
      </tr></thead>
      <tbody>{rows.map(row => <tr key={JSON.stringify([row.production_no, row.nastil, row.factory])}>
        <td>{formatOrderReference(row.order_no)}</td><td>{row.nastil || "—"}</td><td>{handoffFactoryName[row.factory]}</td>
        <td className="tabular-nums">{row.pieces.toLocaleString()}</td>
        {!pending && <><td className="tabular-nums">{row.received_pieces.toLocaleString()}</td>
          <td className="tabular-nums">{(row.pieces - row.received_pieces).toLocaleString()}</td></>}
      </tr>)}</tbody>
    </table>
  </div>;
}

export default function CuttingSewingHandoff({ department, onDispatch }: {
  department: string; onDispatch: () => void;
}) {
  const { lang, t } = useT();
  const copy = cuttingHandoffText[lang];
  const { me } = useMe();
  const { mutate } = useSWRConfig();
  const canSend = can(me, "cutting.bundles");
  const today = shipmentReportDates("day").from;
  const [day, setDay] = useState(today);
  const [factory, setFactory] = useState<HandoffFactory>("BST");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<DispatchOption | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ error: boolean; text: string } | null>(null);
  const deferredSearch = useDeferredValue(search);
  const scope = `cutting_department_code=${department}`;
  const query = `${scope}&day=${day || today}`;
  const { data: options, error: optionsError, mutate: refreshOptions } = useSWR<DispatchOption[]>(
    canSend ? `/api/bundles/cutting-dispatch-options?${scope}&destination_factory=${factory}&q=${encodeURIComponent(deferredSearch)}` : null,
    fetcher,
  );
  const { data: pending, error: pendingError, mutate: refreshPending } = useSWR<Dispatch[]>(
    `/api/bundles/cutting-handoffs?${scope}&day=${today}&pending=true`, fetcher, { refreshInterval: 30_000 },
  );
  const { data: daily, error: dailyError, mutate: refreshDaily } = useSWR<Dispatch[]>(
    `/api/bundles/cutting-handoffs?${query}`, fetcher, { refreshInterval: 30_000 },
  );

  const visibleOptions = options ?? [];
  const selectableOptions = selected && !visibleOptions.some(row => row.id === selected.id)
    ? [selected, ...visibleOptions] : visibleOptions;

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSend || !selected || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      await api.post(`/api/bundles/cutting-dispatch?${scope}`, { factory, production_batch_id: selected.id });
      setSelected(null);
      setSearch("");
      setNotice({ error: false, text: copy.dispatched });
      onDispatch();
      void Promise.allSettled([
        refreshPending(), refreshDaily(), refreshOptions(),
        mutate(key => typeof key === "string" && (key.startsWith("/api/bundles/cutting-storage-by-order?") || key.startsWith("/api/dashboard/cutting?"))),
      ]);
    } catch (error) {
      setNotice({ error: true, text: error instanceof Error ? error.message : t("page.warehouseMap.actionFailed") });
      void refreshOptions().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  return <section className="card mb-4 space-y-4 p-4" aria-labelledby="cutting-handoff-heading">
    <h2 id="cutting-handoff-heading" className="app-card-title">{copy.handoff}</h2>
    {canSend && <form onSubmit={send}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <label>{copy.destination}
          <select className="input" value={factory} disabled={busy} onChange={event => {
            setFactory(event.target.value as HandoffFactory);
            setSelected(null);
            setSearch("");
          }}>
            <option value="BST">Besttex</option><option value="MIL">Milana</option>
          </select>
        </label>
        <div className="min-w-0 flex-1">
          <label htmlFor="cutting-handoff-nastil">{copy.choose}</label>
          <SearchableSelect inputId="cutting-handoff-nastil" value={selected?.id ?? null}
            onChange={value => setSelected(selectableOptions.find(row => row.id === Number(value)) ?? null)} disabled={busy}
            options={selectableOptions.map(row => ({ value: row.id,
              label: `${formatOrderReference(row.order_no)} · ${row.nastil} · ${row.pieces} ${copy.pieces}`,
            }))} placeholder={copy.search} onSearchChange={setSearch} serverFilter
            noResultsText={t("page.search.noMatches")} />
        </div>
        <button className="btn btn-primary" disabled={busy || !selected}>{copy.send}</button>
      </div>
      {optionsError && <p role="alert" className="mt-2 text-red-700">{optionsError.message}</p>}
      {notice && <p role={notice.error ? "alert" : "status"} className={notice.error ? "mt-2 text-red-700" : "mt-2"}>
        {notice.text}
      </p>}
    </form>}
    <div>
      <h3 className="font-semibold">{copy.inTransit}</h3>
      {pendingError ? <p role="alert" className="text-red-700">{pendingError.message}</p>
        : pending ? <DispatchTable rows={pending} pending /> : <p role="status">{t("common.loading")}</p>}
    </div>
    <div className="border-t border-[#ecebe3] pt-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h3 className="font-semibold">{copy.daily}</h3>
        <div className="flex flex-wrap items-end gap-2">
          <label>{copy.reportDate}
            <input className="input" type="date" value={day} onChange={event => setDay(event.target.value)} />
          </label>
          <a className="btn" href={`/api/bundles/cutting-handoffs/export.csv?${query}`} download>
            <Download size={16} />{copy.download}
          </a>
        </div>
      </div>
      {dailyError ? <p role="alert" className="text-red-700">{dailyError.message}</p>
        : daily ? <DispatchTable rows={daily} pending={false} /> : <p role="status">{t("common.loading")}</p>}
    </div>
  </section>;
}
