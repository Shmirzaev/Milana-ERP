"use client";
import { useState } from "react";
import useSWR, { mutate } from "swr";
import ReceivePackagesByOrder from "@/components/ReceivePackagesByOrder";
import Modal from "@/components/Modal";
import ManualPackageReceipt from "@/components/ManualPackageReceipt";
import ReturnPackages from "@/components/ReturnPackages";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { packageReturnText } from "@/lib/packageReturnText";
import { useDialogs } from "@/components/DialogProvider";
import { formatOrderReference } from "@/lib/orderRef";
import { formatModelVariantCode } from "@/lib/variantDisplay";

type ReceiptOption = {
  key: string; code: string | null; run_no: string; package_ids: number[];
  count: number; quantity: number; packages: { id: number; package_no: string }[];
  context: { production_no?: string; sales_order_no?: string; model_code?: string; model_name?: string };
};

export default function ReceivePackages() {
  const { me } = useMe(); const { lang, t } = useT(); const c = packageReturnText[lang]; const dialogs = useDialogs();
  const [open, setOpen] = useState(false); const [query, setQuery] = useState(""); const [search, setSearch] = useState("");
  const [page, setPage] = useState(1); const [busy, setBusy] = useState<string | null>(null); const [message, setMessage] = useState("");
  const { data, error, mutate: refresh } = useSWR<{ rows: ReceiptOption[]; has_more: boolean }>(open ? `/api/packages/receiving-options?q=${encodeURIComponent(search)}&page=${page}` : null, fetcher);
  async function refreshWarehouse() {
    await refresh();
    await mutate(key => typeof key === "string" && (key.startsWith("/api/finished-goods") || key.startsWith("/api/packages/storage-map") || key.startsWith("/api/inbox")));
  }
  if (!can(me, "storage.packages")) return null;
  return <><ReceivePackagesByOrder /><button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>{c.receive}</button>
    <Modal open={open} onClose={() => { if (!busy) setOpen(false); }} title={c.receive} wide>
      <div className="mb-4 flex flex-wrap items-center gap-3"><span>{c.manual}:</span><ManualPackageReceipt onCreated={() => { void refreshWarehouse(); }} /></div>
      <h3 className="mb-3 font-medium">{c.existing}</h3>
      <form className="mb-4 flex gap-2" onSubmit={event => { event.preventDefault(); setSearch(query); setPage(1); }}>
        <input className="input min-w-0 flex-1" aria-label={c.search} placeholder={c.search} value={query} onChange={e => setQuery(e.target.value)} />
        <button className="btn">{t("common.search")}</button>
      </form>
      {(error || message) && <p role="status" className="mb-3">{message || error.message}</p>}
      {!data && !error && <p>{c.loading}</p>}
      {data?.rows.length === 0 && <p>{c.empty}</p>}
      <div className="divide-y">{data?.rows.map(row => <div key={row.key} className="py-3">
        <div className="font-medium">{formatOrderReference(row.context.sales_order_no || row.context.production_no)} · {formatModelVariantCode(row.context.model_code)}</div>
        <div className="my-2 text-sm">{row.run_no} · {row.count} {c.packages} · {row.quantity} {c.pieces}</div>
        <details className="mb-3 text-sm"><summary>{c.packages}</summary><div>{row.packages.map(pkg => pkg.package_no).join(", ")}</div></details>
        <div className="flex flex-wrap gap-2"><button className="btn btn-primary" type="button" disabled={!!busy} onClick={async () => {
          if (!(await dialogs.ask({ message: `${row.run_no} · ${row.count} ${c.packages} · ${row.quantity} ${c.pieces}. ${c.receiveConfirm}` }))) return;
          setBusy(row.key); setMessage("");
          try {
            if (row.code) await api.post("/api/packages/print-runs/receive", { code: row.code });
            else await api.post(`/api/packages/${row.package_ids[0]}/receive-storage`, {});
            setMessage(`${c.received}: ${row.run_no}`); await refreshWarehouse();
          } catch (e: unknown) { setMessage(e instanceof Error ? e.message : String(e)); }
          finally { setBusy(null); }
        }}>{c.receive}</button><ReturnPackages packages={row.packages} onReturned={() => { void refreshWarehouse(); }} /></div>
      </div>)}</div>
      <div className="mt-4 flex justify-between gap-2"><button className="btn" disabled={page === 1 || !!busy} onClick={() => setPage(value => value - 1)}>{t("common.previous")}</button><span>{page}</span><button className="btn" disabled={!data?.has_more || !!busy} onClick={() => setPage(value => value + 1)}>{c.more}</button></div>
    </Modal></>;
}
