"use client";
import { useState } from "react";
import useSWR, { mutate } from "swr";
import Modal from "@/components/Modal";
import { useDialogs } from "@/components/DialogProvider";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { warehousePackageText } from "@/lib/warehousePackageText";
import { packageReturnText } from "@/lib/packageReturnText";

type Order = { id: number; production_no: string; sales_order_no?: string; package_ids: number[]; count: number; quantity: number };
export default function ReceivePackagesByOrder() {
  const { me } = useMe(); const { lang, t } = useT(); const c = warehousePackageText[lang]; const p = packageReturnText[lang];
  const dialogs = useDialogs(); const [open, setOpen] = useState(false); const [query, setQuery] = useState("");
  const [search, setSearch] = useState(""); const [page, setPage] = useState(1); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const { data, error, mutate: refresh } = useSWR<{ rows: Order[]; has_more: boolean }>(open ? `/api/packages/receiving-orders?q=${encodeURIComponent(search)}&page=${page}` : null, fetcher);
  if (!can(me, "storage.packages")) return null;
  async function receive(row: Order) {
    if (busy || !(await dialogs.ask({ message: `${row.production_no} · ${row.count} ${p.packages} · ${row.quantity} ${p.pieces}. ${c.confirm}` }))) return;
    setBusy(true); setMessage("");
    try {
      await api.post(`/api/packages/receive-order/${row.id}`, { package_ids: row.package_ids });
      setMessage(p.received); await refresh();
      await mutate(key => typeof key === "string" && ["/api/packages", "/api/finished-goods", "/api/inbox"].some(prefix => key.startsWith(prefix)));
    } catch (caught) { setMessage(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }
  return <><button className="btn" type="button" onClick={() => setOpen(true)}>{c.byOrder}</button>
    <Modal open={open} onClose={() => { if (!busy) setOpen(false); }} title={c.byOrder} wide>
      <form className="mb-4 flex gap-2" onSubmit={event => { event.preventDefault(); setSearch(query); setPage(1); }}>
        <input className="input flex-1 min-w-0" aria-label={t("common.search")} value={query} onChange={event => setQuery(event.target.value)} />
        <button className="btn" disabled={busy}>{t("common.search")}</button>
      </form>
      {(message || error) && <p role="status">{message || error.message}</p>}
      {!data && !error && <p>{p.loading}</p>}{data?.rows.length === 0 && <p>{p.empty}</p>}
      <div className="divide-y">{data?.rows.map(row => <div key={row.id} className="py-3 flex flex-wrap items-center justify-between gap-3">
        <div><p>{row.production_no}{row.sales_order_no ? ` · ${row.sales_order_no}` : ""}</p><p className="text-sm">{row.count} {p.packages} · {row.quantity} {p.pieces}</p>{row.count > 500 && <p>{c.tooMany}</p>}</div>
        <button className="btn btn-primary" type="button" disabled={busy || row.count > 500} onClick={() => void receive(row)}>{c.receive}</button>
      </div>)}</div>
      <div className="mt-4 flex justify-between"><button className="btn" disabled={busy || page === 1} onClick={() => setPage(value => value - 1)}>{t("common.previous")}</button><span>{page}</span><button className="btn" disabled={busy || !data?.has_more} onClick={() => setPage(value => value + 1)}>{p.more}</button></div>
    </Modal></>;
}
