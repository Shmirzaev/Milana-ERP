"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import WarehouseMap from "@/components/WarehouseMap";

export default function ShipmentsPage() {
  const { t } = useT();
  const { data, mutate } = useSWR<any[]>("/api/shipments", fetcher);
  const { data: orders } = useSWR<any[]>("/api/sales-orders", fetcher);

  const [salesOrderId, setSoId] = useState(0);
  const [pid, setPid] = useState(0);
  const [activeShip, setActive] = useState(0);
  const [modelQuery, setModelQuery] = useState("");
  const [selectedCell, setSelectedCell] = useState<string | null>(null);

  const { data: readyPkgs } = useSWR<any[]>(
    salesOrderId > 0 ? `/api/shipments/ready-packages?sales_order_id=${salesOrderId}` : null,
    fetcher,
  );
  const mapQueryPath = modelQuery.trim()
    ? `/api/packages/storage-map?model_query=${encodeURIComponent(modelQuery.trim())}`
    : "/api/packages/storage-map";
  const { data: mapData, mutate: mutateMap } = useSWR<any>(mapQueryPath, fetcher);

  const filteredPlacements = useMemo(() => {
    const placements = mapData?.placements || [];
    let rows = placements;
    if (selectedCell) rows = rows.filter((p: any) => p.storage_cell === selectedCell);
    if (modelQuery.trim()) rows = rows.filter((p: any) => p.matched);
    return rows;
  }, [mapData?.placements, selectedCell, modelQuery]);

  async function create() {
    const sh = await api.post("/api/shipments", { sales_order_id: salesOrderId || null });
    setActive(sh.id);
    mutate();
  }

  async function addPkg() {
    if (!pid) return;
    await api.post(`/api/shipments/${activeShip}/add-package?package_id=${pid}`);
    mutate();
    mutateMap();
  }

  async function addAllReady() {
    await api.post(`/api/shipments/${activeShip}/add-ready-packages`);
    mutate();
    mutateMap();
  }

  async function ship() {
    await api.post(`/api/shipments/${activeShip}/ship`);
    mutate();
    mutateMap();
  }

  async function deliver() {
    await api.post(`/api/shipments/${activeShip}/deliver`);
    mutate();
    mutateMap();
  }

  return (
    <div>
      <PageHeader title={t("page.shipments.title")} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,430px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="card flex flex-wrap items-end gap-3 p-4">
            <div>
              <label className="label">{t("page.shipments.salesOrder")}</label>
              <select className="input" value={salesOrderId} onChange={(e) => setSoId(Number(e.target.value))}>
                <option value={0}>-</option>
                {orders?.map((o) => <option key={o.id} value={o.id}>{o.order_no}</option>)}
              </select>
            </div>
            <button className="btn btn-primary" onClick={create}>{t("btn.createShipment")}</button>
            {activeShip > 0 && (
              <>
                <div>
                  <label className="label">{t("page.shipments.packageId")}</label>
                  <select className="input" value={pid} onChange={(e) => setPid(Number(e.target.value))}>
                    <option value={0}>-</option>
                    {(readyPkgs || []).map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.package_no} ({p.model_code || p.model_id}) {p.storage_cell ? `@ ${p.storage_cell}/${p.storage_shelf || "S1"}` : ""} {t("field.qty")} {p.total_quantity}
                      </option>
                    ))}
                  </select>
                </div>
                <button className="btn" onClick={addPkg}>{t("btn.addPackage")}</button>
                <button className="btn" onClick={addAllReady}>{t("page.shipments.addAllReady")}</button>
                <button className="btn" onClick={ship}>{t("btn.ship")}</button>
                <button className="btn btn-primary" onClick={deliver}>{t("btn.markDelivered")}</button>
              </>
            )}
          </div>

          <div className="card overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.shipmentNo")}</th>
                  <th>{t("field.status")}</th>
                  <th>{t("field.shipped")}</th>
                  <th>{t("field.delivered")}</th>
                </tr>
              </thead>
              <tbody>
                {data?.map((s) => (
                  <tr key={s.id} className={s.id === activeShip ? "bg-yellow-50" : ""}>
                    <td>{s.shipment_no}</td>
                    <td><span className="badge">{statusLabel(s.status, t)}</span></td>
                    <td>{s.shipped_at ? new Date(s.shipped_at).toLocaleString() : "-"}</td>
                    <td>{s.delivered_at ? new Date(s.delivered_at).toLocaleString() : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-4">
          <div className="card p-4">
            <div className="mb-3 flex flex-wrap items-end gap-2">
              <div className="flex-1">
                <label className="label">{t("page.shipments.findByModelPackage")}</label>
                <input
                  className="input"
                  placeholder={t("ph.modelPackageBarcodeSearch")}
                  value={modelQuery}
                  onChange={(e) => setModelQuery(e.target.value)}
                />
              </div>
              {selectedCell && <button className="btn" onClick={() => setSelectedCell(null)}>{t("btn.clearCell")}</button>}
            </div>
            <WarehouseMap
              cells={mapData?.cells || []}
              selectedCell={selectedCell}
              onSelectCell={(cellCode) => setSelectedCell(cellCode)}
              compact
            />
          </div>

          <div className="card overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.packageNo")}</th>
                  <th>{t("field.model")}</th>
                  <th>{t("field.cell")}</th>
                  <th>{t("field.shelf")}</th>
                  <th>{t("field.qty")}</th>
                  <th>{t("field.status")}</th>
                </tr>
              </thead>
              <tbody>
                {filteredPlacements.map((row: any) => (
                  <tr key={row.id}>
                    <td>{row.package_no}</td>
                    <td>{row.model_code || row.model_id}</td>
                    <td>{row.storage_cell}</td>
                    <td>{row.storage_shelf || "-"}</td>
                    <td>{row.total_quantity}</td>
                    <td>{statusLabel(row.status, t)}</td>
                  </tr>
                ))}
                {filteredPlacements.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-sm text-slate-500">
                      {t("page.shipments.noMapMatches")}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
