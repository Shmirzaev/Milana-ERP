"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { ArrowLeft, ClipboardCheck, PackageCheck, Pencil, Save, Scissors, Shirt } from "lucide-react";

import Modal from "@/components/Modal";
import PageHeader from "@/components/PageHeader";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type WorkOrder = { id: number; operation: "cutting" | "sewing" | "packaging"; status: string; planned_quantity: number; passed_quantity: number; failed_quantity: number };
type Order = {
  id: number;
  order_no: string;
  status: string;
  customer_name: string;
  customer_reference: string | null;
  model: { id: number; code: string; name: string } | null;
  planned_quantity: number;
  deadline: string | null;
  material_description: string | null;
  material_usage_kg: number | null;
  material_notes: string | null;
  handover_recipient: string | null;
  handover_notes: string | null;
  handed_over_at: string | null;
  package_count: number;
  package_quantity: number;
  packed_quantity: number;
  ready_for_handover: boolean;
  items: Array<{ id: number; color: string; size: string; planned_quantity: number }>;
  work_orders: WorkOrder[];
};

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: value.includes("T") ? "short" : undefined }).format(new Date(value));
}

function stageIcon(operation: WorkOrder["operation"]) {
  if (operation === "cutting") return <Scissors className="h-4 w-4" />;
  if (operation === "sewing") return <Shirt className="h-4 w-4" />;
  return <PackageCheck className="h-4 w-4" />;
}

export default function UslugaOrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { t } = useT();
  const { me } = useMe();
  const canManage = can(me, "usluga.manage", "*");
  const canHandover = can(me, "usluga.handover", "*");
  const { data: order, error, isLoading, mutate } = useSWR<Order>(id ? `/api/usluga/orders/${id}` : null, fetcher);
  const [material, setMaterial] = useState({ usage: "", description: "", notes: "" });
  const [handoverOpen, setHandoverOpen] = useState(false);
  const [handover, setHandover] = useState({ recipient: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!order) return;
    setMaterial({ usage: order.material_usage_kg == null ? "" : String(order.material_usage_kg), description: order.material_description || "", notes: order.material_notes || "" });
  }, [order]);

  async function saveMaterial() {
    if (!order) return;
    setBusy(true);
    setMessage("");
    try {
      await api.patch(`/api/usluga/orders/${order.id}/material`, {
        material_usage_kg: Number(material.usage || 0),
        material_description: material.description.trim() || null,
        material_notes: material.notes.trim() || null,
      });
      await mutate();
      setMessage(t("usluga.materialSaved"));
    } catch (submitError: unknown) {
      setMessage(String((submitError as Error)?.message || submitError));
    } finally {
      setBusy(false);
    }
  }

  async function confirmHandover() {
    if (!order) return;
    setBusy(true);
    setMessage("");
    try {
      await api.post(`/api/usluga/orders/${order.id}/handover`, handover);
      await mutate();
      setHandoverOpen(false);
    } catch (submitError: unknown) {
      setMessage(String((submitError as Error)?.message || submitError));
    } finally {
      setBusy(false);
    }
  }

  if (isLoading) return <div className="p-6 text-sm text-[#8a8472]">{t("common.loading")}</div>;
  if (error || !order) return <div className="p-6 text-sm text-red-700">{t("usluga.loadFailed")}</div>;

  return <div>
    <PageHeader
      title={order.order_no}
      subtitle={`${order.customer_name} · ${order.model?.code || "—"} · ${order.planned_quantity.toLocaleString()}`}
      actions={<div className="flex flex-wrap gap-2">
        <Link href="/usluga" className="btn"><ArrowLeft className="h-4 w-4" />{t("usluga.backToPlanning")}</Link>
        {order.model && <Link href={`/usluga/models/${order.model.id}`} className="btn">{t("usluga.openModel")}</Link>}
        {canManage && !order.handed_over_at && <Link href={`/usluga/orders/${order.id}/edit`} className="btn"><Pencil className="h-4 w-4" />{t("btn.edit")}</Link>}
        {canHandover && order.ready_for_handover && <button className="btn btn-primary" onClick={() => { setHandover({ recipient: order.customer_name, notes: "" }); setHandoverOpen(true); }}><ClipboardCheck className="h-4 w-4" />{t("usluga.handOver")}</button>}
      </div>}
    />

    <div className="mb-5 border-y border-[#dedbd0] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">{t("usluga.inventoryBoundary")}</div>

    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-4">
        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4"><h2 className="text-base font-semibold">{t("usluga.productionRoute")}</h2></div>
          <div className="divide-y divide-[#ecebe3]">
            {order.work_orders.map((workOrder) => <Link key={workOrder.id} href={`/work-orders/${workOrder.id}/${workOrder.operation}`} className="grid gap-3 p-4 hover:bg-[#fbfaf6] sm:grid-cols-[180px_120px_minmax(0,1fr)] sm:items-center">
              <span className="flex items-center gap-2 font-medium">{stageIcon(workOrder.operation)}{t(`usluga.status.${workOrder.operation}`)}</span>
              <span className="text-sm text-[#56503f]">{workOrder.status}</span>
              <span className="text-sm tabular-nums text-[#56503f]">{workOrder.passed_quantity.toLocaleString()} / {workOrder.planned_quantity.toLocaleString()}</span>
            </Link>)}
          </div>
        </section>

        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4"><h2 className="text-base font-semibold">{t("usluga.plannedLines")}</h2></div>
          <div className="overflow-x-auto"><table className="table"><thead><tr><th>{t("common.color")}</th><th>{t("common.size")}</th><th>{t("field.quantity")}</th></tr></thead><tbody>{order.items.map((item) => <tr key={item.id}><td>{item.color}</td><td>{item.size}</td><td className="tabular-nums">{item.planned_quantity.toLocaleString()}</td></tr>)}</tbody></table></div>
        </section>

        <section className="card p-4">
          <div className="mb-4 flex items-center justify-between gap-3"><h2 className="text-base font-semibold">{t("usluga.materialEvidence")}</h2>{canManage && !order.handed_over_at && <button className="btn" onClick={() => void saveMaterial()} disabled={busy}><Save className="h-4 w-4" />{t("common.save")}</button>}</div>
          <div className="grid gap-4 md:grid-cols-2">
            <label><span className="label">{t("usluga.materialUsed")}</span><input className="input" type="number" min="0" step="0.01" value={material.usage} onChange={(event) => setMaterial({ ...material, usage: event.target.value })} disabled={!canManage || Boolean(order.handed_over_at)} /></label>
            <label><span className="label">{t("usluga.materialDescription")}</span><input className="input" value={material.description} onChange={(event) => setMaterial({ ...material, description: event.target.value })} disabled={!canManage || Boolean(order.handed_over_at)} /></label>
            <label className="md:col-span-2"><span className="label">{t("usluga.materialNotes")}</span><textarea className="input min-h-20" value={material.notes} onChange={(event) => setMaterial({ ...material, notes: event.target.value })} disabled={!canManage || Boolean(order.handed_over_at)} /></label>
          </div>
          {message && <div className="mt-3 text-sm text-[#56503f]">{message}</div>}
        </section>
      </div>

      <aside className="card p-4">
        <h2 className="text-base font-semibold">{t("usluga.orderSummary")}</h2>
        <dl className="mt-4 space-y-3 text-sm">
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("field.status")}</dt><dd>{t(`usluga.status.${order.status}`)}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.customer")}</dt><dd className="text-right">{order.customer_name}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.customerReference")}</dt><dd>{order.customer_reference || "—"}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("field.deadline")}</dt><dd>{formatDate(order.deadline)}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("field.quantity")}</dt><dd className="tabular-nums">{order.planned_quantity.toLocaleString()}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.packages")}</dt><dd>{order.package_count} / {order.package_quantity.toLocaleString()}</dd></div>
          <div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.packedQuantity")}</dt><dd>{order.packed_quantity.toLocaleString()}</dd></div>
          {order.handed_over_at && <><div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.recipient")}</dt><dd className="text-right">{order.handover_recipient || "—"}</dd></div><div className="flex justify-between gap-4"><dt className="text-[#8a8472]">{t("usluga.handedOverAt")}</dt><dd>{formatDate(order.handed_over_at)}</dd></div></>}
        </dl>
      </aside>
    </div>

    <Modal open={handoverOpen} onClose={() => setHandoverOpen(false)} title={t("usluga.handOver")}>
      <div className="space-y-3"><label><span className="label">{t("usluga.recipient")}</span><input className="input" value={handover.recipient} onChange={(event) => setHandover({ ...handover, recipient: event.target.value })} /></label><label><span className="label">{t("field.notes")}</span><textarea className="input min-h-20" value={handover.notes} onChange={(event) => setHandover({ ...handover, notes: event.target.value })} /></label></div>
      {message && <div className="mt-3 text-sm text-red-700">{message}</div>}
      <div className="mt-4 flex justify-end gap-2"><button className="btn" onClick={() => setHandoverOpen(false)}>{t("btn.cancel")}</button><button className="btn btn-primary" onClick={() => void confirmHandover()} disabled={busy}>{busy ? t("common.saving") : t("usluga.confirmHandover")}</button></div>
    </Modal>
  </div>;
}
