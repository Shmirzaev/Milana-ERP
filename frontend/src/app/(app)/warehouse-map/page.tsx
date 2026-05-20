"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import WarehouseMap from "@/components/WarehouseMap";

export default function WarehouseMapPage() {
  const { t } = useT();
  const [modelQuery, setModelQuery] = useState("");
  const [selectedCell, setSelectedCell] = useState<string | null>(null);

  const mapQueryPath = modelQuery.trim()
    ? `/api/packages/storage-map?model_query=${encodeURIComponent(modelQuery.trim())}`
    : "/api/packages/storage-map";
  const { data: mapData } = useSWR<any>(mapQueryPath, fetcher);

  const filteredPlacements = useMemo(() => {
    const placements = mapData?.placements || [];
    let rows = placements;
    if (selectedCell) rows = rows.filter((p: any) => p.storage_cell === selectedCell);
    if (modelQuery.trim()) rows = rows.filter((p: any) => p.matched);
    return rows;
  }, [mapData?.placements, selectedCell, modelQuery]);

  return (
    <div>
      <PageHeader
        title={t("page.warehouseMap.title")}
        subtitle={t("page.warehouseMap.subtitle")}
      />
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
  );
}
