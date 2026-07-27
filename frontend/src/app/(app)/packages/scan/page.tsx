"use client";

import { useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { CheckSquare, MapPin, PackageCheck, Trash2 } from "lucide-react";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";
import { storageThumbnailUrl } from "@/lib/modelImages";
import WarehouseMap from "@/components/WarehouseMap";

type ScannedPackage = {
  id: number;
  package_no: string;
  barcode?: string | null;
  production_order_id?: number | null;
  production_no?: string | null;
  order_no?: string | null;
  sales_order_no?: string | null;
  model_id?: number | null;
  model_code?: string | null;
  model_name?: string | null;
  model_image_url?: string | null;
  color?: string | null;
  total_quantity?: number | null;
  weight_kg?: number | null;
  status: string;
  storage_cell?: string | null;
  storage_shelf?: string | null;
  items?: Array<{ id?: number; size: string; quantity: number }>;
};

function latestPackageScan(raw: string) {
  const text = String(raw || "").trim();
  if (!text) return "";

  const packagePayloads = text.match(/PACKAGE:[^|\s]+(?:\|(?:(?!PACKAGE:)\S)*)?/gi);
  if (!packagePayloads?.length) return text;
  return packagePayloads[packagePayloads.length - 1].trim();
}

function packageScanError(error: any, t: (key: string) => string) {
  const message = String(error?.message || "").trim();
  if (/^404:/i.test(message) || /package not found/i.test(message)) {
    return t("page.packageScan.notFound");
  }
  return message.replace(/^\d{3}:\s*/, "") || t("page.packageScan.lookupFailed");
}

function packageOrderLabel(pkg: ScannedPackage) {
  return pkg.order_no || pkg.sales_order_no || pkg.production_no || (pkg.production_order_id ? `#${pkg.production_order_id}` : "-");
}

function packageModelLabel(pkg: ScannedPackage) {
  return [pkg.model_code || pkg.model_id, pkg.model_name].filter(Boolean).join(" - ") || "-";
}

const BLOCKED_MAP_MOVE_STATUSES = new Set(["shipped", "delivered", "damaged"]);

export default function ScanPackagePage() {
  const { t } = useT();
  const { me } = useMe();
  const codeInputRef = useRef<HTMLInputElement>(null);
  const [code, setCode] = useState("");
  const [scannedPackages, setScannedPackages] = useState<ScannedPackage[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [activePackageId, setActivePackageId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState<"lookup" | "receive" | "move" | null>(null);
  const [selectedCell, setSelectedCell] = useState<string>("");
  const [selectedShelf, setSelectedShelf] = useState<"S1" | "S2">("S1");
  const { data: mapData, mutate: mutateMap } = useSWR<any>(
    "/api/packages/storage-map",
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const canStoragePackages = can(me, "*", "storage.packages");

  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedPackages = useMemo(
    () => scannedPackages.filter((pkg) => selectedIdSet.has(pkg.id)),
    [scannedPackages, selectedIdSet],
  );
  const packedPackages = useMemo(
    () => scannedPackages.filter((pkg) => pkg.status === "packed"),
    [scannedPackages],
  );
  const activePackage = useMemo(
    () => scannedPackages.find((pkg) => pkg.id === activePackageId) || scannedPackages[0] || null,
    [activePackageId, scannedPackages],
  );
  const sameModelOnMap = useMemo(() => {
    if (!activePackage?.model_id || !mapData?.placements) return [];
    return mapData.placements.filter((row: any) => row.model_id === activePackage.model_id);
  }, [activePackage?.model_id, mapData?.placements]);
  const totalQty = scannedPackages.reduce((sum, pkg) => sum + Number(pkg.total_quantity || 0), 0);

  function selectCodeInput() {
    window.requestAnimationFrame(() => {
      const input = codeInputRef.current;
      if (!input) return;
      input.focus();
      input.select();
    });
  }

  function toggleSelected(packageId: number) {
    setSelectedIds((prev) => (
      prev.includes(packageId)
        ? prev.filter((id) => id !== packageId)
        : [...prev, packageId]
    ));
  }

  function removePackage(packageId: number) {
    setScannedPackages((prev) => prev.filter((pkg) => pkg.id !== packageId));
    setSelectedIds((prev) => prev.filter((id) => id !== packageId));
    setActivePackageId((prev) => (prev === packageId ? null : prev));
  }

  async function lookup(rawCode = code) {
    const scanCode = latestPackageScan(rawCode);
    if (!scanCode || busy) return;
    setCode(scanCode);
    setMsg("");
    setBusy("lookup");
    try {
      const pkg = await api.get<ScannedPackage>(`/api/packages/barcode/${encodeURIComponent(scanCode)}`);
      setScannedPackages((prev) => {
        const exists = prev.some((row) => row.id === pkg.id);
        const rows = exists
          ? prev.map((row) => (row.id === pkg.id ? pkg : row))
          : [pkg, ...prev];
        setMsg(exists ? t("page.packageScan.alreadyInQueue") : t("page.packageScan.addedToQueue"));
        return rows;
      });
      setSelectedIds((prev) => (prev.includes(pkg.id) ? prev : [...prev, pkg.id]));
      setActivePackageId(pkg.id);
      if (pkg.storage_cell) setSelectedCell(pkg.storage_cell);
      if (pkg.storage_shelf === "S2") setSelectedShelf("S2");
      setCode("");
    } catch (e: any) {
      setMsg(packageScanError(e, t));
    } finally {
      setBusy(null);
      selectCodeInput();
    }
  }

  async function receiveSelected() {
    if (!canStoragePackages) return;
    if (!selectedPackages.length) {
      setMsg(t("page.packageScan.selectPackagesFirst"));
      return;
    }
    if (!selectedCell) {
      setMsg(t("page.packageScan.selectCellBeforeBatchReceive"));
      return;
    }
    const blocked = selectedPackages.find((pkg) => pkg.status !== "packed");
    if (blocked) {
      setMsg(t("page.packageScan.onlyPackedCanReceive"));
      return;
    }
    setBusy("receive");
    setMsg("");
    try {
      const result = await api.post<{ count: number; packages: ScannedPackage[] }>("/api/packages/batch/receive-storage", {
        package_ids: selectedPackages.map((pkg) => pkg.id),
        storage_cell: selectedCell,
        storage_shelf: selectedShelf,
      }, 30_000);
      const updatedById = new Map(result.packages.map((pkg) => [pkg.id, pkg]));
      setScannedPackages((prev) => prev.map((pkg) => updatedById.get(pkg.id) || pkg));
      setSelectedIds([]);
      await mutateMap();
      setMsg(t("page.packageScan.batchReceiveSuccess", { count: result.count }));
    } catch (e: any) {
      setMsg(packageScanError(e, t));
    } finally {
      setBusy(null);
      selectCodeInput();
    }
  }

  async function moveSelected() {
    if (!canStoragePackages) return;
    if (!selectedPackages.length) {
      setMsg(t("page.packageScan.selectPackagesFirst"));
      return;
    }
    if (!selectedCell) {
      setMsg(t("page.packageScan.selectCellBeforeBatchReceive"));
      return;
    }
    const blocked = selectedPackages.find((pkg) => BLOCKED_MAP_MOVE_STATUSES.has(pkg.status));
    if (blocked) {
      setMsg(t("page.packageScan.cannotMoveSelected"));
      return;
    }
    setBusy("move");
    setMsg("");
    try {
      const result = await api.post<{ count: number; packages: ScannedPackage[] }>("/api/packages/batch/place-on-map", {
        package_ids: selectedPackages.map((pkg) => pkg.id),
        storage_cell: selectedCell,
        storage_shelf: selectedShelf,
      }, 30_000);
      const updatedById = new Map(result.packages.map((pkg) => [pkg.id, pkg]));
      setScannedPackages((prev) => prev.map((pkg) => updatedById.get(pkg.id) || pkg));
      setSelectedIds([]);
      await mutateMap();
      setMsg(t("page.packageScan.batchMoveSuccess", { count: result.count, cell: selectedCell, shelf: selectedShelf }));
    } catch (e: any) {
      setMsg(packageScanError(e, t));
    } finally {
      setBusy(null);
      selectCodeInput();
    }
  }

  function selectAllScanned() {
    setSelectedIds(scannedPackages.map((pkg) => pkg.id));
  }

  function selectPackedOnly() {
    setSelectedIds(packedPackages.map((pkg) => pkg.id));
  }

  function clearQueue() {
    setScannedPackages([]);
    setSelectedIds([]);
    setActivePackageId(null);
    setMsg("");
    selectCodeInput();
  }

  return (
    <div>
      <PageHeader title={t("page.packageScan.title")} subtitle={t("page.packageScan.subtitle")} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(560px,700px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="card p-4">
            <div className="flex flex-col gap-3 lg:flex-row">
              <input
                ref={codeInputRef}
                className="input"
                autoFocus
                placeholder={t("ph.packageBarcode")}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                onFocus={(e) => e.currentTarget.select()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    lookup(e.currentTarget.value);
                  }
                }}
              />
              <button className="btn btn-primary shrink-0" onClick={() => lookup()} disabled={busy === "lookup"}>
                {busy === "lookup" ? t("common.loading") : t("btn.lookup")}
              </button>
            </div>
            {msg && <div className="mt-3 text-sm text-[#56503f]">{msg}</div>}
          </div>

          <div className="card p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-semibold text-[#14110b]">{t("page.packageScan.queueTitle")}</div>
                <div className="text-xs text-[#8a8472]">
                  {t("page.packageScan.queueSummary", {
                    packages: scannedPackages.length,
                    selected: selectedPackages.length,
                    qty: totalQty,
                  })}
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn h-8 px-2 text-xs" onClick={selectPackedOnly} disabled={!packedPackages.length}>
                  <CheckSquare className="h-3.5 w-3.5" />
                  {t("page.packageScan.selectPacked")}
                </button>
                <button type="button" className="btn h-8 px-2 text-xs" onClick={selectAllScanned} disabled={!scannedPackages.length}>
                  {t("page.packageScan.selectAll")}
                </button>
                <button type="button" className="btn h-8 px-2 text-xs" onClick={clearQueue} disabled={!scannedPackages.length}>
                  <Trash2 className="h-3.5 w-3.5" />
                  {t("common.clear")}
                </button>
              </div>
            </div>

            <div className="mb-3 rounded-md border border-[#e3dfd3] bg-[#f8f6ef] p-3">
              <div className="grid grid-cols-1 gap-2 lg:grid-cols-[minmax(0,1fr)_88px_auto_auto]">
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
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={receiveSelected}
                  disabled={!canStoragePackages || Boolean(busy) || !selectedPackages.length || !selectedCell}
                >
                  <PackageCheck className="h-4 w-4" />
                  {busy === "receive" ? t("page.packageScan.receivingSelected") : t("page.packageScan.receiveSelected")}
                </button>
                <button
                  type="button"
                  className="btn"
                  onClick={moveSelected}
                  disabled={!canStoragePackages || Boolean(busy) || !selectedPackages.length || !selectedCell}
                >
                  <MapPin className="h-4 w-4" />
                  {busy === "move" ? t("page.packageScan.movingSelected") : t("page.packageScan.moveSelected")}
                </button>
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="table min-w-[680px]">
                <thead>
                  <tr>
                    <th className="w-10">{t("field.actions")}</th>
                    <th>{t("field.packageNo")}</th>
                    <th>{t("field.orderNo")}</th>
                    <th>{t("field.model")}</th>
                    <th>{t("field.qty")}</th>
                    <th>{t("field.status")}</th>
                    <th>{t("field.cell")}</th>
                    <th className="text-right">{t("common.remove")}</th>
                  </tr>
                </thead>
                <tbody>
                  {scannedPackages.map((pkg) => {
                    const isSelected = selectedIdSet.has(pkg.id);
                    const imageUrl = storageThumbnailUrl(pkg.model_image_url, 160);
                    return (
                      <tr key={pkg.id} className={activePackage?.id === pkg.id ? "bg-[#f8f6ef]" : ""} onClick={() => setActivePackageId(pkg.id)}>
                        <td>
                          <input
                            type="checkbox"
                            className="h-4 w-4"
                            checked={isSelected}
                            onChange={() => toggleSelected(pkg.id)}
                            onClick={(e) => e.stopPropagation()}
                          />
                        </td>
                        <td>
                          <div className="font-medium text-[#14110b]">{pkg.package_no}</div>
                          <div className="text-xs text-[#8a8472]">{pkg.barcode || "-"}</div>
                        </td>
                        <td>
                          <div className="font-medium text-[#14110b]">{packageOrderLabel(pkg)}</div>
                          <div className="text-xs text-[#8a8472]">{pkg.production_no || "-"}</div>
                        </td>
                        <td>
                          <div className="flex items-center gap-2">
                            {imageUrl ? (
                              <img src={imageUrl} alt={pkg.model_name || pkg.model_code || ""} className="h-12 w-12 rounded-md border border-[#e3dfd3] object-cover" />
                            ) : (
                              <div className="flex h-12 w-12 items-center justify-center rounded-md border border-[#e3dfd3] bg-[#f8f6ef] text-[10px] text-[#8a8472]">
                                {t("page.packageScan.noImage")}
                              </div>
                            )}
                            <div>
                              <div className="max-w-[220px] truncate font-medium text-[#14110b]" title={packageModelLabel(pkg)}>{packageModelLabel(pkg)}</div>
                              <div className="text-xs text-[#8a8472]">{pkg.color || "-"}</div>
                            </div>
                          </div>
                        </td>
                        <td>{Number(pkg.total_quantity || 0)}</td>
                        <td><span className="badge">{statusLabel(pkg.status, t)}</span></td>
                        <td>{pkg.storage_cell ? `${pkg.storage_cell}/${pkg.storage_shelf || "S1"}` : "-"}</td>
                        <td className="text-right">
                          <button
                            type="button"
                            className="btn h-8 px-2 text-xs"
                            onClick={(e) => {
                              e.stopPropagation();
                              removePackage(pkg.id);
                            }}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                  {!scannedPackages.length && (
                    <tr>
                      <td colSpan={8} className="text-sm text-[#8a8472]">{t("page.packageScan.emptyQueue")}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="card p-4">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-[#14110b]">{t("page.packageScan.mapTitle")}</h3>
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
              selectedCell={selectedCell || null}
              onSelectCell={(cellCode) => setSelectedCell(cellCode)}
              compact
            />
          </div>

          {activePackage && (
            <div className="card p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-[#14110b]">{packageModelLabel(activePackage)}</div>
                  <div className="text-xs text-[#8a8472]">{activePackage.package_no} · {packageOrderLabel(activePackage)}</div>
                </div>
                <button type="button" className="btn h-8 px-2 text-xs" onClick={() => api.openLabel(`/api/packages/${activePackage.id}/label`)}>
                  {t("btn.printLabel")}
                </button>
              </div>
              {activePackage.items?.length ? (
                <div className="mb-3 flex flex-wrap gap-2">
                  {activePackage.items.map((item) => (
                    <span key={`${item.id || item.size}-${item.quantity}`} className="rounded-md border border-[#e3dfd3] px-2 py-1 text-xs text-[#56503f]">
                      {item.size}: {item.quantity}
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="overflow-x-auto">
                <table className="table">
                  <thead>
                    <tr>
                      <th>{t("field.packageNo")}</th>
                      <th>{t("field.cell")}</th>
                      <th>{t("field.qty")}</th>
                      <th>{t("field.status")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sameModelOnMap.map((row: any) => (
                      <tr key={row.id} className={row.id === activePackage.id ? "bg-[#f8f6ef]" : ""}>
                        <td>{row.package_no}</td>
                        <td>{row.storage_cell}{row.storage_shelf ? `/${row.storage_shelf}` : ""}</td>
                        <td>{row.total_quantity}</td>
                        <td>{statusLabel(row.status, t)}</td>
                      </tr>
                    ))}
                    {sameModelOnMap.length === 0 && (
                      <tr>
                        <td colSpan={4} className="text-sm text-[#8a8472]">{t("page.packageScan.noModelPackagesOnMap")}</td>
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
