"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { Boxes, Grid2X2, ImageOff, PackageSearch, Search, Warehouse } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type StoragePlacement = {
  id: number;
  package_no: string;
  barcode?: string | null;
  production_order_id?: number | null;
  production_no?: string | null;
  sales_order_id?: number | null;
  sales_order_no?: string | null;
  model_id?: number | null;
  model_code?: string | null;
  model_name?: string | null;
  model_image_url?: string | null;
  color?: string | null;
  package_type?: string | null;
  total_quantity: number;
  status: string;
  storage_cell?: string | null;
  storage_shelf?: string | null;
  location?: string | null;
};

type StorageMapResponse = {
  summary?: {
    cells_occupied?: number;
    packages_on_map?: number;
  };
  placements?: StoragePlacement[];
};

type DetailRow = {
  key: string;
  model_id?: number | null;
  model_code?: string | null;
  model_name?: string | null;
  model_image_url?: string | null;
  order_no: string;
  section: string;
  storage_cell: string;
  storage_shelf: string;
  color?: string | null;
  status: string;
  total_quantity: number;
  package_count: number;
  packages: Array<{ id: number; package_no: string }>;
};

function clean(value?: string | number | null) {
  return String(value ?? "").trim().toLowerCase();
}

function sectionFromCell(cell?: string | null) {
  const code = String(cell || "").trim();
  return code ? code.split("-")[0] : "-";
}

function storageShelf(value?: string | null) {
  return value || "S1";
}

function colorToHex(color?: string | null) {
  if (!color) return "#a8a395";
  const value = color.toLowerCase();
  if (value.includes("black")) return "#45423a";
  if (value.includes("white")) return "#e6e1d5";
  if (value.includes("blue")) return "#7fa7cc";
  if (value.includes("green") || value.includes("mint")) return "#8fc0a2";
  if (value.includes("pink") || value.includes("rose")) return "#d99bae";
  if (value.includes("beige")) return "#ccb796";
  if (value.includes("grey") || value.includes("gray")) return "#9f9fa7";
  return "#b6b09e";
}

function packageListText(packages: DetailRow["packages"]) {
  const names = packages.map((p) => p.package_no).filter(Boolean);
  if (names.length <= 3) return names.join(", ");
  return `${names.slice(0, 3).join(", ")} +${names.length - 3}`;
}

export default function WarehouseStockPage() {
  const { t } = useT();
  const [query, setQuery] = useState("");
  const { data, isLoading } = useSWR<StorageMapResponse>("/api/packages/storage-map", fetcher);

  const placements = useMemo(() => data?.placements || [], [data?.placements]);
  const filtered = useMemo(() => {
    const q = clean(query);
    if (!q) return placements;
    return placements.filter((row) => {
      const fields = [
        row.sales_order_no,
        row.production_no,
        row.model_code,
        row.model_name,
        row.package_no,
        row.barcode,
        row.color,
        row.storage_cell,
        row.storage_shelf,
        row.status,
      ];
      return fields.some((field) => clean(field).includes(q));
    });
  }, [placements, query]);

  const totals = useMemo(() => {
    const modelKeys = new Set<string>();
    const sectionKeys = new Set<string>();
    let totalQty = 0;
    for (const row of filtered) {
      modelKeys.add(String(row.model_id || row.model_code || row.model_name || row.package_no));
      sectionKeys.add(sectionFromCell(row.storage_cell));
      totalQty += Number(row.total_quantity || 0);
    }
    sectionKeys.delete("-");
    return {
      models: modelKeys.size,
      packages: filtered.length,
      quantity: totalQty,
      sections: sectionKeys.size,
    };
  }, [filtered]);

  const modelGroups = useMemo(() => {
    const map = new Map<
      string,
      {
        key: string;
        model_id?: number | null;
        model_code?: string | null;
        model_name?: string | null;
        model_image_url?: string | null;
        package_count: number;
        total_quantity: number;
        sections: Set<string>;
        orders: Set<string>;
        colors: Set<string>;
      }
    >();

    for (const row of filtered) {
      const key = String(row.model_id || row.model_code || row.model_name || row.package_no);
      const existing = map.get(key) || {
        key,
        model_id: row.model_id,
        model_code: row.model_code,
        model_name: row.model_name,
        model_image_url: row.model_image_url,
        package_count: 0,
        total_quantity: 0,
        sections: new Set<string>(),
        orders: new Set<string>(),
        colors: new Set<string>(),
      };
      existing.package_count += 1;
      existing.total_quantity += Number(row.total_quantity || 0);
      existing.sections.add(sectionFromCell(row.storage_cell));
      existing.orders.add(row.sales_order_no || row.production_no || t("page.warehouseStock.unassignedOrder"));
      if (row.color) existing.colors.add(row.color);
      if (!existing.model_image_url && row.model_image_url) existing.model_image_url = row.model_image_url;
      map.set(key, existing);
    }

    return Array.from(map.values()).sort((a, b) => b.total_quantity - a.total_quantity);
  }, [filtered, t]);

  const detailRows = useMemo<DetailRow[]>(() => {
    const map = new Map<string, DetailRow>();
    for (const row of filtered) {
      const section = sectionFromCell(row.storage_cell);
      const shelf = storageShelf(row.storage_shelf);
      const orderNo = row.sales_order_no || row.production_no || t("page.warehouseStock.unassignedOrder");
      const key = [
        row.model_id || row.model_code || row.model_name || "-",
        orderNo,
        section,
        row.storage_cell || "-",
        shelf,
        row.color || "-",
        row.status || "-",
      ].join("|");
      const existing = map.get(key) || {
        key,
        model_id: row.model_id,
        model_code: row.model_code,
        model_name: row.model_name,
        model_image_url: row.model_image_url,
        order_no: orderNo,
        section,
        storage_cell: row.storage_cell || "-",
        storage_shelf: shelf,
        color: row.color,
        status: row.status,
        total_quantity: 0,
        package_count: 0,
        packages: [],
      };
      existing.total_quantity += Number(row.total_quantity || 0);
      existing.package_count += 1;
      existing.packages.push({ id: row.id, package_no: row.package_no });
      if (!existing.model_image_url && row.model_image_url) existing.model_image_url = row.model_image_url;
      map.set(key, existing);
    }
    return Array.from(map.values()).sort((a, b) => {
      const byModel = String(a.model_code || "").localeCompare(String(b.model_code || ""));
      if (byModel !== 0) return byModel;
      const byOrder = a.order_no.localeCompare(b.order_no);
      if (byOrder !== 0) return byOrder;
      return `${a.storage_cell}-${a.storage_shelf}`.localeCompare(`${b.storage_cell}-${b.storage_shelf}`);
    });
  }, [filtered, t]);

  return (
    <div>
      <PageHeader title={t("page.warehouseStock.title")} subtitle={t("page.warehouseStock.subtitle")} />

      <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="kpi-card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="label">{t("page.warehouseStock.products")}</div>
              <div className="mono mt-1 text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.models}</div>
            </div>
            <PackageSearch className="h-5 w-5 text-[#8a8472]" />
          </div>
        </div>
        <div className="kpi-card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="label">{t("page.warehouseStock.totalPacks")}</div>
              <div className="mono mt-1 text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.packages.toLocaleString()}</div>
            </div>
            <Boxes className="h-5 w-5 text-[#8a8472]" />
          </div>
        </div>
        <div className="kpi-card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="label">{t("page.warehouseStock.totalPieces")}</div>
              <div className="mono mt-1 text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.quantity.toLocaleString()}</div>
            </div>
            <Warehouse className="h-5 w-5 text-[#8a8472]" />
          </div>
        </div>
        <div className="kpi-card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="label">{t("page.warehouseStock.sectionsUsed")}</div>
              <div className="mono mt-1 text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.sections}</div>
            </div>
            <Grid2X2 className="h-5 w-5 text-[#8a8472]" />
          </div>
        </div>
      </div>

      <div className="card mb-5 p-4">
        <label className="label">{t("common.search")}</label>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
          <input
            className="input pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("page.warehouseStock.searchPlaceholder")}
          />
        </div>
      </div>

      <div className="mb-5">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="app-card-title">{t("page.warehouseStock.stockByModel")}</h2>
          <span className="text-xs text-[#8a8472]">{t("common.matches", { count: detailRows.length })}</span>
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-4">
          {modelGroups.slice(0, 8).map((group) => (
            <article key={group.key} className="overflow-hidden rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] shadow-sm">
              <div className="grid min-h-[132px] grid-cols-[104px_minmax(0,1fr)]">
                <div className="bg-[#f1efe8]">
                  {group.model_image_url ? (
                    <img src={group.model_image_url} alt={group.model_name || group.model_code || ""} className="h-full min-h-[132px] w-full object-cover" loading="lazy" />
                  ) : (
                    <div className="flex h-full min-h-[132px] items-center justify-center border-r border-[#e3dfd3] text-[#8a8472]">
                      <ImageOff className="h-6 w-6" />
                    </div>
                  )}
                </div>
                <div className="flex min-w-0 flex-col p-3">
                  <div className="mono text-xs font-semibold uppercase text-[#8a8472]">{group.model_code || group.model_id || "-"}</div>
                  <div className="mt-1 line-clamp-2 text-sm font-semibold leading-snug text-[#14110b]">{group.model_name || t("page.models.noPreview")}</div>
                  <div className="mt-auto grid grid-cols-2 gap-2 pt-3 text-xs text-[#56503f]">
                    <div>
                      <div className="label mb-0">{t("field.packages")}</div>
                      <div className="mono font-semibold text-[#14110b]">{group.package_count}</div>
                    </div>
                    <div>
                      <div className="label mb-0">{t("field.totalQty")}</div>
                      <div className="mono font-semibold text-[#14110b]">{group.total_quantity.toLocaleString()}</div>
                    </div>
                  </div>
                  <div className="mt-2 truncate text-xs text-[#8a8472]">
                    {t("field.section")}: {Array.from(group.sections).filter((v) => v !== "-").join(", ") || "-"}
                  </div>
                </div>
              </div>
            </article>
          ))}
          {!isLoading && modelGroups.length === 0 && (
            <div className="rounded-lg border border-dashed border-[#ded9ca] bg-[#fdfcf8] p-8 text-center text-sm text-[#8a8472]">
              {t("page.warehouseStock.noPackages")}
            </div>
          )}
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="border-b border-[#ecebe3] p-4">
          <div className="app-card-title">{t("page.warehouseStock.stockDetail")}</div>
        </div>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.modelPicture")}</th>
                <th>{t("field.modelNumber")}</th>
                <th>{t("field.orderNo")}</th>
                <th>{t("field.section")}</th>
                <th>{t("field.cell")}</th>
                <th>{t("field.shelf")}</th>
                <th>{t("field.color")}</th>
                <th>{t("field.packages")}</th>
                <th>{t("field.totalQty")}</th>
                <th>{t("field.status")}</th>
              </tr>
            </thead>
            <tbody>
              {detailRows.map((row) => (
                <tr key={row.key}>
                  <td>
                    {row.model_image_url ? (
                      <img src={row.model_image_url} alt={row.model_name || row.model_code || ""} className="h-12 w-12 rounded-md border border-[#e3dfd3] object-cover" loading="lazy" />
                    ) : (
                      <div className="flex h-12 w-12 items-center justify-center rounded-md border border-[#e3dfd3] bg-[#f1efe8] text-[#8a8472]">
                        <ImageOff className="h-4 w-4" />
                      </div>
                    )}
                  </td>
                  <td>
                    <div className="mono font-semibold text-[#14110b]">{row.model_code || row.model_id || "-"}</div>
                    <div className="max-w-[220px] truncate text-xs text-[#8a8472]">{row.model_name || "-"}</div>
                  </td>
                  <td className="mono">{row.order_no}</td>
                  <td className="mono font-semibold text-[#14110b]">{row.section}</td>
                  <td className="mono">{row.storage_cell}</td>
                  <td className="mono">{row.storage_shelf}</td>
                  <td>
                    <div className="flex min-w-[90px] items-center gap-1.5">
                      <span className="h-3 w-3 shrink-0 rounded-full border border-black/10" style={{ background: colorToHex(row.color) }} />
                      <span className="truncate">{row.color || "-"}</span>
                    </div>
                  </td>
                  <td>
                    <div className="mono font-semibold text-[#14110b]">{row.package_count}</div>
                    <div className="max-w-[260px] truncate text-xs text-[#8a8472]">
                      {row.packages.length === 1 ? (
                        <Link href={`/packages/${row.packages[0].id}`} className="hover:underline">
                          {row.packages[0].package_no}
                        </Link>
                      ) : (
                        packageListText(row.packages)
                      )}
                    </div>
                  </td>
                  <td className="mono font-semibold text-[#14110b]">{row.total_quantity.toLocaleString()}</td>
                  <td><span className="badge">{statusLabel(row.status, t)}</span></td>
                </tr>
              ))}
              {detailRows.length === 0 && (
                <tr>
                  <td colSpan={10} className="text-sm text-slate-400">
                    {isLoading ? t("common.loading") : t("page.warehouseStock.noPackages")}
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
