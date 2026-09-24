"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import useSWRInfinite from "swr/infinite";
import { Boxes, Grid2X2, ImageOff, PackageSearch, Search, Warehouse } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import StocktakeLink from "@/components/StocktakeLink";
import { statusLabel } from "@/components/StagePipeline";
import { fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { formatOrderReference } from "@/lib/orderRef";

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

type WarehouseStockPage = {
  rows: DetailRow[];
  model_groups: Array<{
    key?: string;
    model_id: number;
    model_code: string;
    model_name: string;
    model_image_url?: string | null;
    package_count: number;
    total_quantity: number;
    sections: string[];
  }>;
  summary: { models: number; packages: number; quantity: number; sections: number };
  total: number;
  offset: number;
  page_size: number;
  has_more: boolean;
};

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

function packageListText(packages: DetailRow["packages"], packageCount: number) {
  const names = packages.map((p) => p.package_no).filter(Boolean);
  const visible = names.slice(0, 3);
  const remaining = Math.max(0, packageCount - visible.length);
  return remaining > 0 ? `${visible.join(", ")} +${remaining}` : visible.join(", ");
}

export default function WarehouseStockPage() {
  const { t } = useT();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  const pageKey = (index: number, previous: WarehouseStockPage | null) => {
    if (index > 0 && previous && !previous.has_more) return null;
    const params = new URLSearchParams({ offset: String(index * 50), page_size: "50", include_unplaced: "true" });
    if (appliedQuery) params.set("query", appliedQuery);
    if (createdFrom) params.set("created_from", createdFrom);
    if (createdTo) params.set("created_to", createdTo);
    return `/api/packages/warehouse-stock?${params.toString()}`;
  };
  const { data: pages, setSize, isLoading, isValidating, error } = useSWRInfinite<WarehouseStockPage>(pageKey, fetcher);
  useEffect(() => {
    void setSize(1);
  }, [appliedQuery, createdFrom, createdTo, setSize]);
  const detailRows = useMemo(() => pages?.flatMap((page) => page.rows) || [], [pages]);
  const firstPage = pages?.[0];
  const totals = firstPage?.summary || { models: 0, packages: 0, quantity: 0, sections: 0 };
  const modelGroups = firstPage?.model_groups || [];
  const hasMore = pages?.[pages.length - 1]?.has_more || false;
  const isLoadingMore = Boolean(pages && isValidating);

  return (
    <div>
      <PageHeader title={t("page.warehouseStock.title")} subtitle={t("page.warehouseStock.subtitle")} actions={<StocktakeLink />} />

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
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(280px,1fr)_12rem_12rem]">
          <div>
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
          <label className="block">
            <span className="label">{t("common.createdFrom")}</span>
            <input className="input" type="date" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)} />
          </label>
          <label className="block">
            <span className="label">{t("common.createdTo")}</span>
            <input className="input" type="date" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)} />
          </label>
        </div>
      </div>

      <div className="mb-5">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="app-card-title">{t("page.warehouseStock.stockByModel")}</h2>
          <span className="text-xs text-[#8a8472]">{t("common.matches", { count: firstPage?.total ?? 0 })}</span>
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2 2xl:grid-cols-4">
          {modelGroups.map((group) => (
            <article key={group.model_id} className="overflow-hidden rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] shadow-sm">
              <div className="grid min-h-[132px] grid-cols-[104px_minmax(0,1fr)]">
                <div className="bg-[#f1efe8]">
                  {group.model_image_url ? (
                    <a href={imagePreviewHref(group.model_image_url, group.model_name || group.model_code || "")} target="_blank" rel="noreferrer" className="block h-full min-h-[132px] w-full">
                      <img src={storageThumbnailUrl(group.model_image_url, 320)} alt={group.model_name || group.model_code || ""} className="h-full min-h-[132px] w-full object-contain p-1" loading="lazy" />
                    </a>
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
                    {t("field.section")}: {group.sections.join(", ") || "-"}
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
        {error && <div role="alert" className="border-b border-red-200 bg-red-50 p-4 text-sm text-red-800">{t("common.error")}</div>}
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
                      <a href={imagePreviewHref(row.model_image_url, row.model_name || row.model_code || "")} target="_blank" rel="noreferrer" className="block h-12 w-12 overflow-hidden rounded-md border border-[#e3dfd3]">
                        <img src={storageThumbnailUrl(row.model_image_url, 160)} alt={row.model_name || row.model_code || ""} className="h-full w-full object-contain p-1" loading="lazy" />
                      </a>
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
                  <td className="mono">{formatOrderReference(row.order_no)}</td>
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
                        <>
                          <Link href={`/packages/${row.packages[0].id}`} className="hover:underline">
                            {row.packages[0].package_no}
                          </Link>
                          {canTraceability && (
                            <Link href={`/traceability?package=${encodeURIComponent(row.packages[0].package_no)}`} className="ml-2 text-brand-600 hover:underline">
                              {t("page.traceability.passport")}
                            </Link>
                          )}
                        </>
                      ) : (
                        packageListText(row.packages, row.package_count)
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
        {hasMore && (
          <div className="border-t border-[#ecebe3] p-4">
            <button
              type="button"
              className="btn"
              disabled={isLoadingMore}
              onClick={() => void setSize((size) => size + 1)}
            >
              {isLoadingMore ? t("common.loading") : t("common.loadMore")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
