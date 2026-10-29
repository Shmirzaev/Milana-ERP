"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import BesttexCutOrderList, { type BesttexCutOrder } from "@/components/BesttexCutOrderList";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { besttexCuttingText } from "@/lib/besttexCutting";

export default function BesttexCutOrders() {
  const { me } = useMe(); const { lang, t } = useT(); const copy = besttexCuttingText[lang];
  const [query, setQuery] = useState(""); const [search, setSearch] = useState(""); const [page, setPage] = useState(1);
  const [printError, setPrintError] = useState(""); const [printing, setPrinting] = useState<number | null>(null);
  const allowed = can(me, "besttex.cutting_sheets") && (me?.factory_code === "BST" || can(me, "*"));
  useEffect(() => { const timer = window.setTimeout(() => { setSearch(query.trim()); setPage(1); }, 250); return () => window.clearTimeout(timer); }, [query]);
  const { data, error, isLoading } = useSWR<{ items: BesttexCutOrder[]; total: number; page_size: number }>(
    allowed ? `/api/besttex/cutting-orders?page=${page}&q=${encodeURIComponent(search)}` : null, fetcher,
  );
  if (!allowed) return <p>{t("auth.accessDenied")}</p>;
  return <main className="space-y-3">
    <h1 className="sr-only">Besttex · {copy.title}</h1>
    <input className="input max-w-lg" type="search" aria-label={copy.search} placeholder={copy.search} value={query} onChange={e => setQuery(e.target.value)} />
    {error && <p role="alert" className="text-red-700">{error.message}</p>}
    {printError && <p role="alert" className="text-red-700">{printError}</p>}
    {isLoading && <p role="status">{t("common.loading")}</p>}
    {data && <><BesttexCutOrderList rows={data.items} total={data.total} lang={lang} t={t} printing={printing} onPrint={async recordId => {
        setPrinting(recordId); setPrintError("");
        try { await api.openLabel(`/api/besttex/cutting-orders/${recordId}/sheet`); }
        catch (error) { setPrintError(error instanceof Error ? error.message : String(error)); }
        finally { setPrinting(null); }
      }} />
      <div className="flex items-center gap-3"><button className="btn" disabled={page === 1} onClick={() => setPage(page - 1)}>{copy.previous}</button>
        <span>{page} / {Math.max(1, Math.ceil(data.total / data.page_size))} · {data.total}</span>
        <button className="btn" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>{copy.next}</button></div>
    </>}
  </main>;
}
