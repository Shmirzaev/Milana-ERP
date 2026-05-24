"use client";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

export default function BundlesPage() {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data: pageData } = useSWR<any>(`/api/bundles?include_total=true&page=${page}&page_size=${pageSize}`, fetcher);
  const data: any[] = pageData?.rows || [];
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const visibleBundles = useMemo(
    () => (data || []).filter((b) => String(b?.status || "") !== "received_sewing"),
    [data],
  );

  const grouped = useMemo(() => {
    const map = new Map<string, { key: string; items: any[]; totalQty: number }>();
    for (const b of visibleBundles) {
      const key = b.production_no || `PO-${b.production_order_id}`;
      const group = map.get(key);
      if (group) {
        group.items.push(b);
        group.totalQty += Number(b.quantity || 0);
      } else {
        map.set(key, { key, items: [b], totalQty: Number(b.quantity || 0) });
      }
    }
    return Array.from(map.values());
  }, [visibleBundles]);

  function toggleGroup(key: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div>
      <PageHeader title={t("page.bundles.title")} subtitle={t("page.bundles.subtitle")} actions={<Link href="/bundles/scan" className="btn">{t("btn.scan")}</Link>} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.bundleNo")}</th>
              <th>{t("field.productionNo")}</th>
              <th>{t("field.barcode")}</th>
              <th>{t("field.model")}</th>
              <th>{t("field.color")}</th>
              <th>{t("field.size")}</th>
              <th>{t("field.qty")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {grouped.map((g) => {
              const isOpen = openGroups.has(g.key);
              return (
                <Fragment key={`group-${g.key}`}>
                  <tr className="bg-[#f8f6ef]">
                    <td colSpan={9} className="py-1">
                      <button
                        type="button"
                        className="w-full text-left text-xs font-semibold uppercase tracking-wide text-slate-700"
                        onClick={() => toggleGroup(g.key)}
                      >
                        <span className="mr-2">{isOpen ? "[-]" : "[+]"}</span>
                        {t("field.productionNo")}: {g.key} | {t("common.total")}: {g.items.length} {t("field.bundleNo")} | {t("field.qty")}: {g.totalQty}
                      </button>
                    </td>
                  </tr>
                  {isOpen && g.items.map((b) => (
                    <tr key={b.id}>
                      <td className="font-medium">{b.bundle_no}</td>
                      <td>{b.production_no || b.production_order_id}</td>
                      <td><code>{b.barcode}</code></td>
                      <td>{b.model_id}</td>
                      <td>{b.color}</td>
                      <td>{b.size}</td>
                      <td>{b.quantity}</td>
                      <td><span className="badge">{statusLabel(b.status, t)}</span></td>
                      <td className="flex gap-2">
                        <Link className="text-brand-600 hover:underline" href={`/bundles/${b.id}`}>{t("btn.view")}</Link>
                        <button type="button" className="text-slate-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${b.id}/label`)}>{t("btn.label")}</button>
                      </td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
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
