"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function ShipmentsPage() {
  const { t } = useT();
  const { data, mutate } = useSWR<any[]>("/api/shipments", fetcher);
  const { data: orders } = useSWR<any[]>("/api/sales-orders", fetcher);
  const [salesOrderId, setSoId] = useState(0);
  const [pid, setPid] = useState(0);
  const [activeShip, setActive] = useState(0);
  async function create() {
    const sh = await api.post("/api/shipments", { sales_order_id: salesOrderId || null });
    setActive(sh.id);
    mutate();
  }
  async function addPkg() { await api.post(`/api/shipments/${activeShip}/add-package?package_id=${pid}`); mutate(); }
  async function ship() { await api.post(`/api/shipments/${activeShip}/ship`); mutate(); }
  async function deliver() { await api.post(`/api/shipments/${activeShip}/deliver`); mutate(); }
  return (
    <div>
      <PageHeader title={t("page.shipments.title")} />
      <div className="card p-4 mb-6 flex flex-wrap gap-3 items-end">
        <div>
          <label className="label">{t("page.shipments.salesOrder")}</label>
          <select className="input" value={salesOrderId} onChange={(e) => setSoId(Number(e.target.value))}>
            <option value={0}>—</option>
            {orders?.map((o) => <option key={o.id} value={o.id}>{o.order_no}</option>)}
          </select>
        </div>
        <button className="btn btn-primary" onClick={create}>{t("btn.createShipment")}</button>
        {activeShip > 0 && <>
          <div><label className="label">{t("page.shipments.packageId")}</label><input className="input" type="number" value={pid} onChange={(e) => setPid(Number(e.target.value))} /></div>
          <button className="btn" onClick={addPkg}>{t("btn.addPackage")}</button>
          <button className="btn" onClick={ship}>{t("btn.ship")}</button>
          <button className="btn btn-primary" onClick={deliver}>{t("btn.markDelivered")}</button>
        </>}
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.shipmentNo")}</th><th>{t("field.status")}</th><th>{t("field.shipped")}</th><th>{t("field.delivered")}</th>
            </tr>
          </thead>
          <tbody>{data?.map((s) => <tr key={s.id} className={s.id === activeShip ? "bg-yellow-50" : ""}><td>{s.shipment_no}</td><td><span className="badge">{s.status}</span></td><td>{s.shipped_at ? new Date(s.shipped_at).toLocaleString() : "—"}</td><td>{s.delivered_at ? new Date(s.delivered_at).toLocaleString() : "—"}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
