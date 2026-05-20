"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import WarehouseMap from "@/components/WarehouseMap";

export default function ScanPackagePage() {
  const { t } = useT();
  const { me } = useMe();
  const [code, setCode] = useState("");
  const [pkg, setPkg] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const [selectedCell, setSelectedCell] = useState<string>("");
  const [selectedShelf, setSelectedShelf] = useState<"S1" | "S2">("S1");
  const { data: mapData, mutate: mutateMap } = useSWR<any>("/api/packages/storage-map", fetcher);
  const canStoragePackages = can(me, "*", "storage.packages");
  const canSalesOrders = can(me, "*", "sales.orders");
  const canShipment = can(me, "*", "storage.shipment");

  async function lookup() {
    setMsg("");
    try {
      const p = await api.get(`/api/packages/barcode/${encodeURIComponent(code.trim())}`);
      setPkg(p);
      setSelectedCell(p.storage_cell || "");
      setSelectedShelf((p.storage_shelf || "S1") as "S1" | "S2");
    } catch (e: any) {
      setPkg(null);
      setMsg(e.message);
    }
  }

  async function act(action: "receive-storage" | "reserve" | "ship" | "mark-delivered" | "mark-damaged") {
    if (!pkg) return;
    try {
      if (action === "receive-storage" && !selectedCell) {
        setMsg(t("page.packageScan.selectCellBeforeReceive"));
        return;
      }
      const body =
        action === "receive-storage"
          ? {
              storage_cell: selectedCell,
              storage_shelf: selectedShelf,
            }
          : undefined;
      const p = await api.post(`/api/packages/${pkg.id}/${action}`, body);
      setPkg(p);
      setSelectedCell(p.storage_cell || "");
      setSelectedShelf((p.storage_shelf || "S1") as "S1" | "S2");
      await mutateMap();
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  async function placeOnMap() {
    if (!pkg || !selectedCell) {
      setMsg(t("page.packageScan.selectCellFirst"));
      return;
    }
    try {
      const p = await api.post(`/api/packages/${pkg.id}/place-on-map`, {
        storage_cell: selectedCell,
        storage_shelf: selectedShelf,
      });
      setPkg(p);
      await mutateMap();
      setMsg(t("page.packageScan.locationUpdated"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  const sameModelOnMap = useMemo(() => {
    if (!pkg?.model_id || !mapData?.placements) return [];
    return mapData.placements.filter((row: any) => row.model_id === pkg.model_id);
  }, [pkg?.model_id, mapData?.placements]);

  const availableActions: Array<{ key: "receive-storage" | "reserve" | "ship" | "mark-delivered" | "mark-damaged"; label: string; primary?: boolean; danger?: boolean }> = [];
  if (pkg?.status === "packed" && canStoragePackages) {
    availableActions.push({ key: "receive-storage", label: t("btn.receiveAtStorage"), primary: true });
  }
  if ((pkg?.status === "received_in_storage" || pkg?.status === "packed") && canSalesOrders) {
    availableActions.push({ key: "reserve", label: t("btn.reserve") });
  }
  if ((pkg?.status === "received_in_storage" || pkg?.status === "reserved") && canShipment) {
    availableActions.push({ key: "ship", label: t("btn.ship") });
  }
  if (pkg?.status === "shipped" && canShipment) {
    availableActions.push({ key: "mark-delivered", label: t("btn.markDelivered") });
  }
  if (canStoragePackages || canShipment) {
    availableActions.push({ key: "mark-damaged", label: t("btn.markDamaged"), danger: true });
  }

  return (
    <div>
      <PageHeader title={t("page.packageScan.title")} subtitle={t("page.packageScan.subtitle")} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,460px)_minmax(0,1fr)]">
        <div className="card p-6">
          <div className="mb-4 flex gap-2">
            <input
              className="input"
              autoFocus
              placeholder={t("ph.packageBarcode")}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") lookup(); }}
            />
            <button className="btn btn-primary" onClick={lookup}>{t("btn.lookup")}</button>
          </div>
          {msg && <div className="mb-3 text-sm">{msg}</div>}
          {pkg && (
            <div>
              <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
                <div className="text-slate-500">{t("field.packageNo")}</div><div>{pkg.package_no}</div>
                <div className="text-slate-500">{t("field.model")}</div><div>{pkg.model_id}</div>
                <div className="text-slate-500">{t("field.color")}</div><div>{pkg.color}</div>
                <div className="text-slate-500">{t("field.totalQty")}</div><div>{pkg.total_quantity}</div>
                <div className="text-slate-500">{t("common.status")}</div><div><span className="badge">{statusLabel(pkg.status, t)}</span></div>
                <div className="text-slate-500">{t("field.cell")}</div><div>{pkg.storage_cell || "-"}</div>
                <div className="text-slate-500">{t("field.shelf")}</div><div>{pkg.storage_shelf || "-"}</div>
              </div>

              <div className="mb-4 rounded-xl border border-[#e3dfd3] bg-[#f8f6ef] p-3">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-[#8a8472]">{t("page.packageScan.placementTitle")}</div>
                <div className="grid grid-cols-1 gap-2 md:grid-cols-[minmax(0,1fr)_110px_auto]">
                  <input
                    className="input"
                    placeholder={t("ph.storageCellCode")}
                    value={selectedCell}
                    onChange={(e) => setSelectedCell(String(e.target.value || "").toUpperCase())}
                  />
                  <select className="input" value={selectedShelf} onChange={(e) => setSelectedShelf(e.target.value as "S1" | "S2")}>
                    <option value="S1">S1</option>
                    <option value="S2">S2</option>
                  </select>
                  {canStoragePackages && (
                    <button
                      type="button"
                      className="btn"
                      onClick={placeOnMap}
                      disabled={!selectedCell || pkg.status === "shipped" || pkg.status === "delivered"}
                    >
                      {t("btn.placeOnMap")}
                    </button>
                  )}
                </div>
              </div>

              {pkg.items && (
                <div className="mb-3">
                  <h4 className="text-sm font-medium">{t("page.packageScan.sizesInside")}</h4>
                  <ul className="text-sm">{pkg.items.map((i: any) => <li key={i.id}>{i.size}: {i.quantity}</li>)}</ul>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {availableActions.map((a) => (
                  <button
                    key={a.key}
                    className={`btn ${a.primary ? "btn-primary" : ""} ${a.danger ? "btn-danger" : ""}`}
                    onClick={() => act(a.key)}
                  >
                    {a.label}
                  </button>
                ))}
                {availableActions.length === 0 && (
                  <div className="text-sm text-slate-500">{t("page.packageScan.noActions")}</div>
                )}
              </div>
              <div className="mt-4">
                <button type="button" className="text-brand-600 hover:underline" onClick={() => api.openLabel(`/api/packages/${pkg.id}/label`)}>{t("btn.printLabel")}</button>
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="card p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold uppercase tracking-[0.08em] text-[#8a8472]">{t("page.packageScan.mapTitle")}</h3>
                <p className="text-xs text-[#8a8472]">{t("page.packageScan.mapHint")}</p>
              </div>
              {mapData?.summary && (
                <div className="text-right text-xs text-[#8a8472]">
                  <div>{t("page.packageScan.occupiedCells", { occupied: mapData.summary.cells_occupied, total: mapData.summary.cells_total })}</div>
                  <div>{t("page.packageScan.packagesOnMap", { count: mapData.summary.packages_on_map })}</div>
                </div>
              )}
            </div>
            <WarehouseMap
              cells={mapData?.cells || []}
              selectedCell={selectedCell || pkg?.storage_cell || null}
              onSelectCell={(cellCode) => setSelectedCell(cellCode)}
              compact
            />
          </div>

          {pkg && (
            <div className="card p-4">
              <h3 className="mb-2 text-sm font-semibold uppercase tracking-[0.08em] text-[#8a8472]">{t("page.packageScan.sameModelOnMap")}</h3>
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("field.packageNo")}</th>
                      <th>{t("field.cell")}</th>
                      <th>{t("field.shelf")}</th>
                      <th>{t("field.qty")}</th>
                      <th>{t("field.status")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sameModelOnMap.map((row: any) => (
                      <tr key={row.id} className={row.id === pkg.id ? "bg-yellow-50" : ""}>
                        <td>{row.package_no}</td>
                        <td>{row.storage_cell}</td>
                        <td>{row.storage_shelf || "-"}</td>
                        <td>{row.total_quantity}</td>
                        <td>{statusLabel(row.status, t)}</td>
                      </tr>
                    ))}
                    {sameModelOnMap.length === 0 && (
                      <tr>
                        <td colSpan={5} className="text-sm text-slate-500">{t("page.packageScan.noModelPackagesOnMap")}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
