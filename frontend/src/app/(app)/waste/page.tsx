"use client";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { useDialogs } from "@/components/DialogProvider";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import { useMe } from "@/lib/auth";
import {
  pendingWasteSale,
  postWasteSale,
  WasteSaleRecoveryError,
  wasteSaleChangedEvent,
  wasteSaleStorageKey,
  type WasteSalePayload,
} from "@/lib/wasteSaleRecovery";

type WasteForm = {
  item_id: number;
  source_department_id: number;
  waste_type: string;
  quantity: NumberInputValue;
  unit: string;
  reason: string;
  sellable: boolean;
};

type SaleForm = { wasteId: number; buyer: string; quantity: string; unitPrice: string };
type WastePage = { rows: any[]; total: number; page: number; page_size: number; has_more: boolean };

export default function WastePage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data: wastePage, mutate } = useSWR<WastePage>(`/api/waste?page=${page}&page_size=${pageSize}`, fetcher);
  const data = wastePage?.rows;
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);
  const { data: depts } = useSWR<any[]>("/api/departments", fetcher);
  const { data: dash } = useSWR<any>("/api/dashboard/waste", fetcher);
  const [f, setF] = useState<WasteForm>({ item_id: 0, source_department_id: 0, waste_type: "fabric", quantity: "", unit: "kg", reason: "", sellable: true });
  const [msg, setMsg] = useState("");
  const [sale, setSale] = useState<SaleForm | null>(null);
  const [sellingId, setSellingId] = useState<number | null>(null);
  const [pendingSaleIds, setPendingSaleIds] = useState<Set<number>>(() => new Set());
  const saleSubmissionRef = useRef(false);

  useEffect(() => {
    if (!me || !data) return;
    const refreshPendingSales = () => {
      const pendingIds = new Set<number>();
      for (const row of data) {
        try {
          if (pendingWasteSale(me.id, row.id)) pendingIds.add(row.id);
        } catch {
          // Corrupt evidence must stay visible and block a replacement request.
          pendingIds.add(row.id);
        }
      }
      setPendingSaleIds(pendingIds);
    };
    refreshPendingSales();
    if (typeof window === "undefined") return;
    const syncPendingSales = (event: Event) => {
      const changedKey = "key" in event ? (event as StorageEvent).key : null;
      if (changedKey && !data.some((row) => changedKey === wasteSaleStorageKey(me.id, row.id))) return;
      refreshPendingSales();
    };
    window.addEventListener("storage", syncPendingSales);
    window.addEventListener(wasteSaleChangedEvent, syncPendingSales);
    return () => {
      window.removeEventListener("storage", syncPendingSales);
      window.removeEventListener(wasteSaleChangedEvent, syncPendingSales);
    };
  }, [data, me]);

  async function record(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try { await api.post("/api/waste", { ...f, quantity: numberOrZero(f.quantity) }); mutate(); setMsg(t("msg.recorded")); }
    catch (e: any) { setMsg(e.message); }
  }
  async function act(id: number, action: string, body?: any) {
    if (action === "request-disposal" && !(await dialogs.ask({ message: t("common.confirmAction") }))) return;
    await api.post(`/api/waste/${id}/${action}`, body); mutate();
  }

  function openSale(wasteId: number) {
    setMsg("");
    let pending: ReturnType<typeof pendingWasteSale> = null;
    try {
      pending = me ? pendingWasteSale(me.id, wasteId) : null;
    } catch (error: unknown) {
      setSale(null);
      setMsg(error instanceof Error ? error.message : t("page.waste.saleFailed"));
      return;
    }
    setSale({
      wasteId,
      buyer: pending?.payload.buyer_name ?? "",
      quantity: pending ? String(pending.payload.quantity) : "",
      unitPrice: pending ? String(pending.payload.unit_price) : "",
    });
  }

  function changePage(nextPage: number) {
    setSale(null);
    setPage(nextPage);
  }

  function changePageSize(nextPageSize: number) {
    setSale(null);
    setPage(1);
    setPageSize(nextPageSize);
  }

  async function submitSale(e: React.FormEvent) {
    e.preventDefault();
    if (!sale || !me || saleSubmissionRef.current) return;
    if (!sale.quantity.trim() || !sale.unitPrice.trim()) {
      setMsg(t("page.waste.saleInvalid"));
      return;
    }
    const payload: WasteSalePayload = {
      buyer_name: sale.buyer.trim(),
      quantity: Number(sale.quantity),
      unit_price: Number(sale.unitPrice),
    };
    if (!payload.buyer_name || payload.buyer_name.length > 255 ||
        !Number.isFinite(payload.quantity) || payload.quantity <= 0 ||
        !Number.isFinite(payload.unit_price) || payload.unit_price < 0) {
      setMsg(t("page.waste.saleInvalid"));
      return;
    }
    saleSubmissionRef.current = true;
    const wasteId = sale.wasteId;
    try {
      try {
        if (!(await dialogs.ask({ message: t("page.waste.saleConfirm") }))) return;
        setSellingId(wasteId);
        setMsg("");
        await postWasteSale(me.id, wasteId, payload);
        setPendingSaleIds((current) => {
          const next = new Set(current);
          next.delete(wasteId);
          return next;
        });
        setSale(null);
        setMsg(t("page.waste.saleRecorded"));
        try {
          await mutate();
        } catch {
          setMsg(t("page.waste.saleRecordedRefreshFailed"));
        }
      } catch (error: unknown) {
        if (error instanceof WasteSaleRecoveryError && error.code === "completed_unavailable") {
          setPendingSaleIds((current) => {
            const next = new Set(current);
            next.delete(wasteId);
            return next;
          });
          setSale(null);
          setMsg(t("page.waste.saleRecoveryResolved"));
          try { await mutate(); } catch { /* The completed-sale warning remains authoritative. */ }
          return;
        }
        if (error instanceof WasteSaleRecoveryError && error.code === "cancelled") {
          setPendingSaleIds((current) => {
            const next = new Set(current);
            next.delete(wasteId);
            return next;
          });
          setMsg(t("page.waste.saleRecoveryCancelled"));
          return;
        }
        let stillPending = true;
        let storageMessage = "";
        try {
          stillPending = Boolean(pendingWasteSale(me.id, wasteId));
        } catch (storageError: unknown) {
          storageMessage = storageError instanceof WasteSaleRecoveryError
            ? t("page.waste.saleRecoveryUnavailable")
            : storageError instanceof Error
              ? storageError.message
              : t("page.waste.saleFailed");
        }
        setPendingSaleIds((current) => {
          const next = new Set(current);
          if (stillPending) next.add(wasteId);
          else next.delete(wasteId);
          return next;
        });
        const recoveryMessage = error instanceof WasteSaleRecoveryError
          ? error.code === "pending"
            ? t("page.waste.pendingSale")
            : t("page.waste.saleRecoveryUnavailable")
          : "";
        setMsg(storageMessage || recoveryMessage || (error instanceof Error ? error.message : t("page.waste.saleFailed")));
      }
    } finally {
      saleSubmissionRef.current = false;
      setSellingId(null);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.waste.title")} />
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.waste.sellable")}</div><div className="text-2xl font-semibold">{dash?.sellable_count ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.waste.nonSellable")}</div><div className="text-2xl font-semibold">{dash?.non_sellable_count ?? 0}</div></div>
      </div>
      <form onSubmit={record} className="card p-4 mb-6 grid grid-cols-1 md:grid-cols-4 gap-3">
        <select className="input" value={f.item_id} onChange={(e) => setF({ ...f, item_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.item")}</option>{items?.map((i) => <option key={i.id} value={i.id}>{i.sku} — {i.name}</option>)}
        </select>
        <select className="input" value={f.source_department_id} onChange={(e) => setF({ ...f, source_department_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.sourceDept")}</option>{depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <input className="input" placeholder={t("page.waste.wasteType")} value={f.waste_type} onChange={(e) => setF({ ...f, waste_type: e.target.value })} />
        <input className="input" type="number" step="0.01" placeholder={t("field.quantity")} value={f.quantity} onChange={(e) => setF({ ...f, quantity: parseNumberInput(e.target.value) })} />
        <input className="input" placeholder={t("field.unit")} value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} />
        <label className="text-sm flex items-center gap-2 mt-1"><input type="checkbox" checked={f.sellable} onChange={(e) => setF({ ...f, sellable: e.target.checked })} />{t("field.sellable")}</label>
        <button className="btn btn-primary md:col-span-1">{t("btn.recordWaste")}</button>
        {msg && <div className="md:col-span-4 text-sm">{msg}</div>}
      </form>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.wasteType")}</th><th>{t("field.qty")}</th><th>{t("field.sellable")}</th>
              <th>{t("field.status")}</th><th>{t("field.value")}</th><th></th>
            </tr>
          </thead>
          <tbody>
            {data?.map((w) => {
              const hasPendingSale = pendingSaleIds.has(w.id);
              return <tr key={w.id}>
                <td>{w.waste_type}</td>
                <td>
                  <span>{Number(w.quantity).toFixed(2)} {w.unit}</span>
                  <div className="text-xs text-slate-500">{t("page.waste.originalQuantity")}</div>
                  <div className="text-xs font-medium text-slate-700">{t("field.remaining")}: {Number(w.remaining_quantity ?? w.quantity).toFixed(2)} {w.unit}</div>
                </td>
                <td>{w.sellable ? t("field.yes") : t("field.no")}</td>
                <td><span className="badge">{statusLabel(w.status, t)}</span></td>
                <td>${Number(w.estimated_value).toFixed(2)}</td>
                <td className="flex gap-2 flex-wrap">
                  {w.status === "recorded" && <button className="text-brand-600 hover:underline" onClick={() => act(w.id, "receive")}>{t("btn.receive")}</button>}
                  {((w.status === "received_by_waste_department" && w.sellable) || hasPendingSale) && <button className="text-green-700 hover:underline" onClick={() => openSale(w.id)}>{hasPendingSale ? t("page.waste.retrySale") : t("page.waste.sell")}</button>}
                  {w.status === "received_by_waste_department" && !w.sellable && <button className="text-yellow-700 hover:underline" onClick={() => act(w.id, "request-disposal", { reason: "Standard disposal" })}>{t("btn.requestDisposal")}</button>}
                  {sale?.wasteId === w.id && <form onSubmit={submitSale} className="w-full min-w-64 space-y-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <label className="block text-xs font-medium text-slate-600">{t("page.waste.buyer")}<input className="input mt-1 w-full" maxLength={255} required value={sale.buyer} onChange={(e) => setSale({ ...sale, buyer: e.target.value })} /></label>
                    <div className="grid grid-cols-2 gap-2">
                      <label className="block text-xs font-medium text-slate-600">{t("field.quantity")}<input className="input mt-1 w-full" type="number" min="0.0001" max={w.remaining_quantity ?? w.quantity} step="0.0001" required value={sale.quantity} onChange={(e) => setSale({ ...sale, quantity: e.target.value })} /></label>
                      <label className="block text-xs font-medium text-slate-600">{t("page.waste.unitPrice")}<input className="input mt-1 w-full" type="number" min="0" step="0.01" required value={sale.unitPrice} onChange={(e) => setSale({ ...sale, unitPrice: e.target.value })} /></label>
                    </div>
                    <p className="text-xs text-slate-500">{t("page.waste.remainingChecked")}</p>
                    <div className="flex gap-2">
                      <button className="btn btn-primary" disabled={sellingId === w.id}>{sellingId === w.id ? t("common.loading") : t("page.waste.confirmSale")}</button>
                      <button type="button" className="btn" disabled={sellingId === w.id} onClick={() => setSale(null)}>{t("btn.cancel")}</button>
                    </div>
                  </form>}
                </td>
              </tr>;
            })}
          </tbody>
        </table>
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={wastePage?.total ?? 0}
          count={data?.length ?? 0}
          onPageChange={changePage}
          onPageSizeChange={changePageSize}
          pageSizeOptions={[25, 50, 100]}
        />
      </div>
    </div>
  );
}
