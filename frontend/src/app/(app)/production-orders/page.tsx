"use client";
import { useDeferredValue, useState } from "react";
import Link from "next/link";
import useSWRInfinite from "swr/infinite";
import { api, fetcher } from "@/lib/api";
import { modelOptionsByIdsFetcher, modelOptionsByIdsKey } from "@/lib/useModelOptions";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { productionTypeLabel, statusLabel } from "@/components/StagePipeline";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import { orderReference } from "@/lib/orderRef";

type PO = {
  id: number; production_no: string; order_no?: string | null; sales_order_no?: string | null; production_type: string;
  model_id: number; status: string; planned_quantity: number;
  deadline: string | null;
};

type ProductionOrderPage = {
  rows: PO[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

const STATUSES = [
  "new", "planning", "waiting_material", "cutting", "printing", "sewing",
  "packaging", "finished_storage", "delivered", "closed", "cancelled",
];

export default function ProductionOrdersPage() {
  const { me } = useMe();
  const { t } = useT();
  const isAdmin = can(me, "*");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const {
    data: pages,
    size,
    setSize,
    mutate,
    isValidating,
  } = useSWRInfinite<ProductionOrderPage>(
    (index, previousPage) => previousPage && !previousPage.has_more
      ? null
      : `/api/production-orders?page=${index + 1}&page_size=50&include_total=true&q=${encodeURIComponent(deferredSearch)}`,
    fetcher,
    { persistSize: false },
  );
  const data = pages?.flatMap((page) => page.rows) ?? [];
  const total = pages?.[0]?.total ?? 0;
  const hasMore = pages?.at(-1)?.has_more ?? false;
  const modelOptionsKey = modelOptionsByIdsKey(data.map((row) => row.model_id));
  const { data: models } = useSWR<any[]>(modelOptionsKey, modelOptionsByIdsFetcher);
  const modelMap = new Map((models ?? []).map((m) => [m.id, m]));

  const [editing, setEditing] = useState<PO | null>(null);
  const [edit, setEdit] = useState<{ status: string; planned_quantity: NumberInputValue; deadline: string }>({ status: "new", planned_quantity: "", deadline: "" });
  const [editMsg, setEditMsg] = useState("");

  function openEdit(p: PO) {
    setEditing(p);
    setEdit({ status: p.status, planned_quantity: p.planned_quantity, deadline: p.deadline ? p.deadline.slice(0, 10) : "" });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try {
      await api.patch(`/api/production-orders/${editing.id}`, {
        status: edit.status,
        planned_quantity: numberOrZero(edit.planned_quantity),
        deadline: edit.deadline ? new Date(edit.deadline).toISOString() : null,
      });
      setEditing(null);
      mutate();
    } catch (e: any) { setEditMsg(e.message); }
  }

  return (
    <div>
      <PageHeader title={t("page.po.title")} />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="input h-9 min-w-48 flex-1"
          aria-label={`${t("common.search")} ${t("page.po.title")}`}
          placeholder={t("common.search")}
          maxLength={100}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <span className="text-xs text-slate-500">{data.length} / {total}</span>
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.orderNo")}</th><th>{t("field.type")}</th><th>{t("field.model")}</th>
              <th>{t("page.poDetail.planned")}</th><th>{t("field.status")}</th>
              <th>{t("field.deadline")}</th><th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((p) => (
              <tr key={p.id}>
                <td className="font-medium">{orderReference(p, p.production_no)}</td>
                <td><span className="badge badge-blue">{productionTypeLabel(p.production_type, t)}</span></td>
                <td>
                  <div className="font-medium text-sm">{modelMap.get(p.model_id)?.code ?? p.model_id}</div>
                  <div className="text-xs text-slate-500">{modelMap.get(p.model_id)?.name ?? ""}</div>
                </td>
                <td>{p.planned_quantity}</td>
                <td><span className="badge">{statusLabel(p.status, t)}</span></td>
                <td>{p.deadline ? new Date(p.deadline).toLocaleDateString() : "—"}</td>
                <td className="flex gap-3">
                  <Link href={`/production-orders/${p.id}`} className="text-brand-600 hover:underline">{t("btn.view")}</Link>
                  {isAdmin && (
                    <button className="text-slate-700 hover:underline" onClick={() => openEdit(p)}>{t("btn.edit")}</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <button
          className="btn btn-secondary mt-3"
          disabled={isValidating}
          onClick={() => setSize(size + 1)}
        >
          {isValidating ? t("common.loading") : t("common.loadMore")}
        </button>
      )}

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.po.editTitle", { productionNo: orderReference(editing, editing?.production_no ?? ""), orderNo: orderReference(editing, editing?.production_no ?? "") })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div>
            <label className="label">{t("field.status")}</label>
            <select className="input" value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              {STATUSES.map((s) => <option key={s} value={s}>{statusLabel(s, t)}</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("field.plannedQty")}</label>
            <input className="input" type="number" value={edit.planned_quantity} onChange={(e) => setEdit({ ...edit, planned_quantity: parseNumberInput(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.deadline")}</label>
            <input className="input" type="date" value={edit.deadline} onChange={(e) => setEdit({ ...edit, deadline: e.target.value })} />
          </div>
          {editMsg && <div className="text-sm text-red-600">{editMsg}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => setEditing(null)}>{t("btn.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("btn.saveChanges")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
