"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";

export default function BundlesPage() {
  const { t } = useT();
  const searchParams = useSearchParams();
  const cuttingDepartment = searchParams.get("cutting_department") === "ECT" ? "ECT" : "CUT";
  const factoryName = cuttingDepartment === "ECT" ? t("factory.ecoCotton") : t("factory.milana");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data: pageData } = useSWR<any>(`/api/bundles?include_total=true&page=${page}&page_size=${pageSize}&cutting_department_code=${cuttingDepartment}`, fetcher);
  const data = useMemo<any[]>(() => pageData?.rows || [], [pageData?.rows]);
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());

  const grouped = useMemo(() => {
    const map = new Map<string, {
      key: string;
      orderNo: string;
      productionBatchId: number | null;
      batchLabel: string;
      trackingPassportNo: string;
      items: any[];
      totalQty: number;
    }>();
    for (const b of data || []) {
      const orderNo = orderReference(b, `#${b.production_order_id}`);
      const productionBatchId = b.production_batch_id ? Number(b.production_batch_id) : null;
      const batchLabel = b.batch_label || (productionBatchId ? `${t("field.batch")} #${productionBatchId}` : "No batch");
      const trackingPassportNo = b.tracking_passport_no || "";
      const key = `${orderNo}::${productionBatchId || "none"}`;
      const group = map.get(key);
      if (group) {
        group.items.push(b);
        group.totalQty += Number(b.quantity || 0);
      } else {
        map.set(key, {
          key,
          orderNo,
          productionBatchId,
          batchLabel,
          trackingPassportNo,
          items: [b],
          totalQty: Number(b.quantity || 0),
        });
      }
    }
    return Array.from(map.values());
  }, [data, t]);

  function toggleGroup(key: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function printGroupLabels(group: { productionBatchId: number | null; items: any[] }) {
    if (group.productionBatchId) {
      api.openLabel(`/api/bundles/label-sheet/by-batch/${group.productionBatchId}`);
      return;
    }

    const ids = group.items.map((item) => item.id).filter(Boolean).join(",");
    if (ids) api.openLabel(`/api/bundles/label-sheet/by-ids?ids=${encodeURIComponent(ids)}`);
  }

  return (
    <div>
      <PageHeader title={`${factoryName} - ${t("page.bundles.title")}`} subtitle={t("page.bundles.subtitle")} actions={<Link href="/bundles/scan" className="btn">{t("btn.scan")}</Link>} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.bundleNo")}</th>
              <th>{t("field.orderNo")}</th>
              <th>{t("field.batch")}</th>
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
                    <td colSpan={10} className="py-2">
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <button
                          type="button"
                          className="text-left text-xs font-semibold uppercase tracking-wide text-slate-700"
                          onClick={() => toggleGroup(g.key)}
                        >
                          <span className="mr-2">{isOpen ? "[-]" : "[+]"}</span>
                          {t("field.orderNo")}: {g.orderNo} | {t("field.batch")}: {g.batchLabel}
                          {g.trackingPassportNo ? ` | ${t("field.trackingPassport")}: ${g.trackingPassportNo}` : ""}
                          {" | "}
                          {t("common.total")}: {g.items.length} {t("field.bundleNo")} | {t("field.qty")}: {g.totalQty}
                        </button>
                        <button
                          type="button"
                          className="btn shrink-0"
                          onClick={() => printGroupLabels(g)}
                        >
                          {t("page.packaging.printAllLabels")}
                        </button>
                      </div>
                    </td>
                  </tr>
                  {isOpen && g.items.map((b) => (
                    <tr key={b.id}>
                      <td className="font-medium">{b.bundle_no}</td>
                      <td>{orderReference(b, `#${b.production_order_id}`)}</td>
                      <td>
                        <div>{b.batch_label || "-"}</div>
                        {b.tracking_passport_no && <div className="text-xs text-slate-500">{b.tracking_passport_no}</div>}
                      </td>
                      <td><code>{b.barcode}</code></td>
                      <td>{b.model_code || b.model_id}</td>
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
