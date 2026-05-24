"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

const DEFAULT_RECEIVE_FORM = {
  item_id: 0,
  batch_no: "",
  supplier_id: 0,
  color: "",
  old_code: "",
  color_code: "",
  color_status: "",
  order_no: "",
  quantity: 0,
  piece_count: 0,
  processes: "",
  unit: "kg",
  cost_per_unit: 0,
  warehouse_id: 0,
  qc_status: "passed",
};

export default function ReceiveStockPage() {
  const { t } = useT();
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);
  const { data: warehouses } = useSWR<any[]>("/api/inventory/warehouses", fetcher);
  const { data: suppliers } = useSWR<any[]>("/api/suppliers", fetcher);
  const { data: batches, mutate: refreshBatches } = useSWR<any[]>("/api/inventory/batches", fetcher);
  const [f, setF] = useState(DEFAULT_RECEIVE_FORM);
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      const payload: any = {
        ...f,
        supplier_id: f.supplier_id || null,
        old_code: f.old_code.trim() || null,
        color_code: f.color_code.trim() || null,
        color_status: f.color_status.trim() || null,
        order_no: f.order_no.trim() || null,
        piece_count: f.piece_count > 0 ? f.piece_count : null,
        processes: f.processes.trim() || null,
      };
      await api.post("/api/inventory/receive", payload);
      setMsg(t("msg.recorded"));
      setF(DEFAULT_RECEIVE_FORM);
      refreshBatches();
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.receiveStock.title")} subtitle={t("page.receiveStock.subtitle")} />
      <form onSubmit={submit} className="card p-6 grid grid-cols-1 md:grid-cols-3 gap-3 max-w-3xl">
        <div>
          <label className="label">{t("field.materialName")}</label>
          <select className="input" value={f.item_id} onChange={(e) => setF({ ...f, item_id: Number(e.target.value) })} required>
            <option value={0}>{t("field.materialName")}</option>
            {items?.map((i) => <option key={i.id} value={i.id}>{i.sku} - {i.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">{t("field.batch")}</label>
          <input className="input" placeholder={t("field.batch")} value={f.batch_no} onChange={(e) => setF({ ...f, batch_no: e.target.value })} required />
        </div>
        <div>
          <label className="label">{t("field.materialColor")}</label>
          <input className="input" placeholder={t("field.materialColor")} value={f.color} onChange={(e) => setF({ ...f, color: e.target.value })} />
        </div>

        <div>
          <label className="label">{t("field.oldCode")}</label>
          <input className="input" placeholder={t("field.oldCode")} value={f.old_code} onChange={(e) => setF({ ...f, old_code: e.target.value })} />
        </div>
        <div>
          <label className="label">{t("field.colorCode")}</label>
          <input className="input" placeholder={t("field.colorCode")} value={f.color_code} onChange={(e) => setF({ ...f, color_code: e.target.value })} />
        </div>
        <div>
          <label className="label">{t("field.colorStatus")}</label>
          <input className="input" placeholder={t("field.colorStatus")} value={f.color_status} onChange={(e) => setF({ ...f, color_status: e.target.value })} />
        </div>

        <div>
          <label className="label">{t("field.orderNo")}</label>
          <input className="input" placeholder={t("field.orderNo")} value={f.order_no} onChange={(e) => setF({ ...f, order_no: e.target.value })} />
        </div>
        <div>
          <label className="label">{t("field.netto")}</label>
          <input className="input" type="number" step="0.01" placeholder={t("field.netto")} value={f.quantity} onChange={(e) => setF({ ...f, quantity: Number(e.target.value) })} required />
        </div>
        <div>
          <label className="label">{t("field.pieceCount")}</label>
          <input className="input" type="number" min={0} placeholder={t("field.pieceCount")} value={f.piece_count} onChange={(e) => setF({ ...f, piece_count: Number(e.target.value) })} />
        </div>

        <div className="md:col-span-3">
          <label className="label">{t("field.processes")}</label>
          <input className="input" placeholder={t("field.processes")} value={f.processes} onChange={(e) => setF({ ...f, processes: e.target.value })} />
        </div>

        <div>
          <label className="label">{t("ph.supplier")}</label>
          <select className="input" value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: Number(e.target.value) })}>
            <option value={0}>{t("ph.supplier")}</option>
            {suppliers?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">{t("field.unit")}</label>
          <input className="input" placeholder={t("field.unit")} value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} />
        </div>
        <div>
          <label className="label">{`${t("field.cost")} / ${t("field.unit")}`}</label>
          <input className="input" type="number" step="0.01" placeholder={t("field.cost") + " / " + t("field.unit")} value={f.cost_per_unit} onChange={(e) => setF({ ...f, cost_per_unit: Number(e.target.value) })} />
        </div>

        <div>
          <label className="label">{t("ph.warehouse")}</label>
          <select className="input" value={f.warehouse_id} onChange={(e) => setF({ ...f, warehouse_id: Number(e.target.value) })} required>
            <option value={0}>{t("ph.warehouse")}</option>
            {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">QC Status</label>
          <select className="input" value={f.qc_status} onChange={(e) => setF({ ...f, qc_status: e.target.value })}>
            <option value="pending">{t("qc.pending")}</option>
            <option value="passed">{t("qc.passed")}</option>
            <option value="failed">{t("qc.failed")}</option>
          </select>
        </div>

        <button className="btn btn-primary md:col-span-3">{t("btn.receive")}</button>
        {msg && <div className="text-sm md:col-span-3">{msg}</div>}
      </form>

      <div className="card mt-4 overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.batch").toUpperCase()}</th>
              <th>{t("field.materialName").toUpperCase()}</th>
              <th>{t("field.materialColor").toUpperCase()}</th>
              <th>{t("field.oldCode").toUpperCase()}</th>
              <th>{t("field.colorCode").toUpperCase()}</th>
              <th>{t("field.colorStatus").toUpperCase()}</th>
              <th>{t("field.orderNo").toUpperCase()}</th>
              <th>{t("field.netto").toUpperCase()}</th>
              <th>{t("field.pieceCount").toUpperCase()}</th>
              <th>{t("field.processes").toUpperCase()}</th>
            </tr>
          </thead>
          <tbody>
            {batches?.slice(0, 30).map((b) => (
              <tr key={b.id}>
                <td>{b.batch_no}</td>
                <td>{b.item_name ? `${b.item_sku || ""} ${b.item_name}`.trim() : b.item_id}</td>
                <td>{b.color || "-"}</td>
                <td>{b.old_code || "-"}</td>
                <td>{b.color_code || "-"}</td>
                <td>{b.color_status || "-"}</td>
                <td>{b.order_no || "-"}</td>
                <td>{Number(b.quantity).toFixed(2)}</td>
                <td>{b.piece_count ?? "-"}</td>
                <td>{b.processes || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
