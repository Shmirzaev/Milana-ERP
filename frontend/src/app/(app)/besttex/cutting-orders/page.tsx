"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Printer } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { besttexCuttingText } from "@/lib/besttexCutting";
import { formatModelVariantCode } from "@/lib/variantDisplay";
import { formatOrderReference } from "@/lib/orderRef";

type Row = { cutting_record_id: number; cutting_batch_no: string | null; production_no: string; order_no: string;
  batch_no: string | null; model_code: string | null; model_name: string | null; cut_pieces: number; passed_pieces: number; created_at: string };

export default function BesttexCutOrders() {
  const { me } = useMe(); const { lang, t } = useT(); const copy = besttexCuttingText[lang];
  const [query, setQuery] = useState(""); const [search, setSearch] = useState(""); const [page, setPage] = useState(1);
  const [printError, setPrintError] = useState(""); const [printing, setPrinting] = useState<number | null>(null);
  const allowed = can(me, "besttex.cutting_sheets") && (me?.factory_code === "BST" || can(me, "*"));
  useEffect(() => { const timer = window.setTimeout(() => { setSearch(query.trim()); setPage(1); }, 250); return () => window.clearTimeout(timer); }, [query]);
  const { data, error, isLoading } = useSWR<{ items: Row[]; total: number; page_size: number }>(
    allowed ? `/api/besttex/cutting-orders?page=${page}&q=${encodeURIComponent(search)}` : null, fetcher,
  );
  if (!allowed) return <p>{t("auth.accessDenied")}</p>;
  return <main className="space-y-3">
    <h1 className="app-page-title">Besttex · {copy.title}</h1><p className="text-sm text-[#56503f]">{copy.help}</p>
    <input className="input max-w-sm" type="search" aria-label={copy.search} placeholder={copy.search} value={query} onChange={e => setQuery(e.target.value)} />
    {error && <p role="alert" className="text-red-700">{error.message}</p>}
    {printError && <p role="alert" className="text-red-700">{printError}</p>}
    {isLoading && <p role="status">{t("common.loading")}</p>}
    {data && <><div className="overflow-x-auto"><table className="table min-w-[800px] text-sm"><thead><tr>
      <th>{copy.order}</th><th>{copy.batch}</th><th>{copy.model}</th><th>{copy.cut}</th><th>{copy.passed}</th><th>{copy.date}</th><th>{copy.print}</th>
    </tr></thead><tbody>{data.items.map(row => <tr key={row.cutting_record_id}>
      <td className="whitespace-nowrap">{formatOrderReference(row.order_no)}</td><td className="whitespace-nowrap">{row.cutting_batch_no || row.batch_no || "—"}</td>
      <td><span className="whitespace-nowrap">{formatModelVariantCode(row.model_code)}</span><div className="text-xs text-[#56503f]">{row.model_name}</div></td>
      <td>{row.cut_pieces}</td><td>{row.passed_pieces}</td><td>{new Date(row.created_at).toLocaleDateString(lang === "uz" ? "uz-UZ" : lang)}</td>
      <td><button type="button" className="btn inline-flex items-center gap-2 whitespace-nowrap" disabled={printing !== null} onClick={async () => {
        setPrinting(row.cutting_record_id); setPrintError("");
        try { await api.openLabel(`/api/besttex/cutting-orders/${row.cutting_record_id}/sheet`); }
        catch (error) { setPrintError(error instanceof Error ? error.message : String(error)); }
        finally { setPrinting(null); }
      }}><Printer className="h-4 w-4" />{copy.print}</button></td>
    </tr>)}</tbody></table></div>
      {!data.items.length && <p>{copy.empty}</p>}
      <div className="flex items-center gap-3"><button className="btn" disabled={page === 1} onClick={() => setPage(page - 1)}>{copy.previous}</button>
        <span>{page} / {Math.max(1, Math.ceil(data.total / data.page_size))} · {data.total}</span>
        <button className="btn" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>{copy.next}</button></div>
    </>}
  </main>;
}
