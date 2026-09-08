"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import StocktakeSession from "@/components/StocktakeSession";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { stocktakeText } from "@/lib/stocktakeText";

export type Count = { id: number; title: string; created_at: string; completed_at: string | null };

export default function StocktakePage() {
  const { lang } = useT();
  const text = stocktakeText[lang];
  const { me, loading } = useMe();
  const allowed = can(me, "storage.packages", "storage.shipment");
  const [offset, setOffset] = useState(0);
  const { data, error, mutate } = useSWR<{ items: Count[]; total: number }>(allowed ? `/api/warehouse-stocktakes?offset=${offset}` : null, fetcher);
  const [selected, setSelected] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const requestKey = useRef<string | null>(null);

  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !title.trim()) return;
    setBusy(true); setFailure("");
    requestKey.current ??= crypto.randomUUID();
    try {
      const count = await api.post<Count>("/api/warehouse-stocktakes", { title: title.trim(), request_key: requestKey.current }, 60000);
      requestKey.current = null; setTitle(""); setSelected(count.id); void mutate();
    } catch (e) { setFailure(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  if (loading || !me) return <p>{text.loading}</p>;
  if (!allowed) return <p>{text.denied}</p>;
  return <div className="space-y-4">
    <PageHeader title={text.title} subtitle={text.intro} actions={<Link className="btn" href="/warehouse-stock">{lang === "ru" ? "Остатки склада" : lang === "uz" ? "Ombor qoldig‘i" : "Warehouse stock"}</Link>} />
    {selected ? <StocktakeSession key={selected} countId={selected} userId={me.id} onBack={() => { setSelected(null); void mutate(); }} /> : <>
      <form className="flex flex-wrap items-end gap-3" onSubmit={start}>
        <label className="flex flex-col gap-1 flex-1 min-w-48">{text.name}<input className="input" value={title} onChange={e => setTitle(e.target.value)} maxLength={120} required disabled={busy} /></label>
        <button className="btn btn-primary" disabled={busy || !title.trim()}>{busy ? text.loading : text.start}</button>
      </form>
      {(failure || error) && <p role="alert" className="text-red-700">{failure || String(error)}</p>}
      <h2 className="text-lg font-medium">{text.history}</h2>
      {!data && !error && <p>{text.loading}</p>}
      {data?.items.length === 0 && <p>{text.empty}</p>}
      <div className="divide-y border-y">
        {data?.items.map(count => <button key={count.id} type="button" onClick={() => setSelected(count.id)} className="w-full text-left py-3 flex flex-wrap justify-between gap-2 hover:bg-[var(--erp-subtle)]">
          <span>{count.title}<span className="block text-sm text-slate-500">{new Date(count.created_at).toLocaleString()}</span></span>
          <span>{count.completed_at ? text.complete : text.open}</span>
        </button>)}
      </div>
      {(data?.total || 0) > 50 && <div className="flex gap-3"><button className="btn" disabled={offset === 0} onClick={() => setOffset(offset - 50)}>{text.previous}</button><button className="btn" disabled={offset + 50 >= (data?.total || 0)} onClick={() => setOffset(offset + 50)}>{text.next}</button></div>}
    </>}
  </div>;
}
