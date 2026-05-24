"use client";
import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { useT } from "@/lib/i18n";

export default function BatchesPage() {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data: pageData } = useSWR<any>(`/api/inventory/batches?include_total=true&page=${page}&page_size=${pageSize}`, fetcher);
  const data: any[] = pageData?.rows || [];
  return (
    <div>
      <PageHeader title={t("page.batches.title")} subtitle={t("page.batches.subtitle")} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.batch").toUpperCase()}</th>
              <th>{t("field.materialName").toUpperCase()}</th>
              <th>{t("field.materialColor").toUpperCase()}</th>
              <th>{t("field.oldCode").toUpperCase()}</th>
              <th>{t("field.colorCode").toUpperCase()}</th>
              <th>{t("field.colorStatus").toUpperCase()}</th>
              <th>{t("field.orderNo").toUpperCase()}</th>
              <th>{t("field.netto").toUpperCase()}</th>
              <th>{t("field.pieceCount").toUpperCase()}</th>
              <th>{t("field.processes").toUpperCase()}</th>
              <th>{t("field.received")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((b) => (
              <tr key={b.id}>
                <td>{b.batch_no}</td>
                <td>{b.item_name ? `${b.item_sku || ""} ${b.item_name}`.trim() : b.item_id}</td>
                <td>{b.color || "-"}</td>
                <td>{b.old_code || "-"}</td>
                <td>{b.color_code || "-"}</td>
                <td>{b.color_status || "-"}</td>
                <td>{b.order_no || "-"}</td>
                <td>{Number(b.quantity).toFixed(2)}</td>
                <td>{b.piece_count ?? "-"}</td>
                <td>{b.processes || "-"}</td>
                <td>{new Date(b.received_date).toLocaleDateString()}</td>
              </tr>
            ))}
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
