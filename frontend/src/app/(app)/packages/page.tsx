"use client";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

export default function PackagesPage() {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data: pageData } = useSWR<any>(`/api/packages?include_total=true&page=${page}&page_size=${pageSize}`, fetcher);
  const data: any[] = pageData?.rows || [];
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => {
    const map = new Map<
      string,
      {
        key: string;
        sales_order_id: number | null;
        production_order_id: number | null;
        total_quantity: number;
        packages: any[];
        latest_id: number;
      }
    >();

    for (const p of data || []) {
      const salesOrderId = p.sales_order_id == null ? null : Number(p.sales_order_id);
      const productionOrderId = p.production_order_id == null ? null : Number(p.production_order_id);
      const key = salesOrderId != null ? `so-${salesOrderId}` : `po-${productionOrderId ?? "none"}`;
      const existing = map.get(key) ?? {
        key,
        sales_order_id: salesOrderId,
        production_order_id: productionOrderId,
        total_quantity: 0,
        packages: [],
        latest_id: 0,
      };
      existing.total_quantity += Number(p.total_quantity || 0);
      existing.packages.push(p);
      existing.latest_id = Math.max(existing.latest_id, Number(p.id || 0));
      map.set(key, existing);
    }

    return Array.from(map.values())
      .map((g) => ({
        ...g,
        packages: [...g.packages].sort((a, b) => String(b.package_no || "").localeCompare(String(a.package_no || ""))),
      }))
      .sort((a, b) => b.latest_id - a.latest_id);
  }, [data]);

  return (
    <div>
      <PageHeader title={t("page.packages.title")} subtitle={t("page.packages.subtitle")} actions={<Link href="/packages/scan" className="btn">{t("btn.scan")}</Link>} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.packageNo")}</th>
              <th>{t("field.barcode")}</th>
              <th>{t("field.model")}</th>
              <th>{t("field.color")}</th>
              <th>{t("field.totalQty")}</th>
              <th>{t("field.cell")}</th>
              <th>{t("field.shelf")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const first = g.packages[0];
              const last = g.packages[g.packages.length - 1];
              const statusVariants = Array.from(new Set(g.packages.map((p) => String(p.status || ""))));
              const sameModel = g.packages.every((p) => p.model_id === first.model_id);
              const sameColor = g.packages.every((p) => p.color === first.color);
              const sameStatus = statusVariants.length === 1;
              const sameCell = g.packages.every((p) => String(p.storage_cell || "") === String(first.storage_cell || ""));
              const sameShelf = g.packages.every((p) => String(p.storage_shelf || "") === String(first.storage_shelf || ""));
              const packageIds = g.packages.map((p) => p.id).join(",");
              const isExpanded = !!expandedGroups[g.key];
              const groupLabel =
                g.sales_order_id != null
                  ? `${t("field.salesOrderShort")} #${g.sales_order_id}`
                  : `${t("field.productionNo")} #${g.production_order_id ?? "-"}`;

              return (
                <Fragment key={g.key}>
                  <tr>
                    <td className="font-medium">
                      <div>{groupLabel}</div>
                      <div className="text-xs text-slate-500">
                        {g.packages.length === 1 ? first.package_no : `${first.package_no} - ${last.package_no}`}
                      </div>
                    </td>
                    <td><code>{g.packages.length}</code></td>
                    <td>{sameModel ? first.model_id : "-"}</td>
                    <td>{sameColor ? first.color : "-"}</td>
                    <td>{g.total_quantity}</td>
                    <td>{sameCell ? (first.storage_cell || "-") : "-"}</td>
                    <td>{sameShelf ? (first.storage_shelf || "-") : "-"}</td>
                    <td>
                      <span className="badge">
                        {sameStatus ? statusLabel(first.status, t) : `${statusLabel(first.status, t)} +${statusVariants.length - 1}`}
                      </span>
                    </td>
                    <td className="flex gap-2">
                      <button
                        type="button"
                        className="text-brand-600 hover:underline"
                        onClick={() => setExpandedGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
                      >
                        {isExpanded ? t("common.close") : t("btn.open")}
                      </button>
                      {g.packages.length > 1 && (
                        <button
                          type="button"
                          className="text-slate-600 hover:underline"
                          onClick={() => api.openLabel(`/api/packages/label-sheet/by-ids?ids=${encodeURIComponent(packageIds)}`)}
                        >
                          {t("btn.print")}
                        </button>
                      )}
                    </td>
                  </tr>
                  {isExpanded && g.packages.map((p) => (
                    <tr key={p.id} className="bg-slate-50">
                      <td className="font-medium">{p.package_no}</td>
                      <td><code>{p.barcode}</code></td>
                      <td>{p.model_id}</td>
                      <td>{p.color}</td>
                      <td>{p.total_quantity}</td>
                      <td>{p.storage_cell || "-"}</td>
                      <td>{p.storage_shelf || "-"}</td>
                      <td><span className="badge">{statusLabel(p.status, t)}</span></td>
                      <td className="flex gap-2">
                        <Link href={`/packages/${p.id}`} className="text-brand-600 hover:underline">{t("btn.view")}</Link>
                        <button type="button" className="text-slate-600 hover:underline" onClick={() => api.openLabel(`/api/packages/${p.id}/label`)}>{t("btn.label")}</button>
                      </td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
            {groups.length === 0 && (
              <tr>
                <td colSpan={9} className="text-sm text-slate-400">
                  {data ? t("page.packages.empty") : t("common.loading")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={Number(pageData?.total || data.length)}
          count={data.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </div>
    </div>
  );
}
