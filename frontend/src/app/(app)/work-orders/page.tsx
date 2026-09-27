"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { useT } from "@/lib/i18n";
import StagePipeline, { operationLabel, statusLabel } from "@/components/StagePipeline";
import { orderReference } from "@/lib/orderRef";

type WorkOrderPage = { rows: any[]; total: number; page: number; page_size: number; has_more: boolean };

export default function WorkOrdersPage() {
  const { t } = useT();
  const searchParams = useSearchParams();
  // Allow ?dept=CUT|PRT|SEW|PKG|FGS to pre-filter from the sidebar.
  const deptCode = searchParams?.get("dept") ?? "";
  const { data: depts } = useSWR<any[]>("/api/departments", fetcher);
  const [dept, setDept] = useState<string>("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Once departments arrive, translate code → id (only if URL had a code).
  useEffect(() => {
    if (!deptCode || !depts) return;
    const match = depts.find((d) => d.code === deptCode);
    if (match) { setDept(String(match.id)); setPage(1); }
  }, [deptCode, depts]);

  const url = `/api/work-orders?page=${page}&page_size=${pageSize}${dept ? `&department_id=${dept}` : ""}`;
  const { data: workOrderPage } = useSWR<WorkOrderPage>(url, fetcher);
  const data = workOrderPage?.rows;
  const sewingFlowKey = data?.some((workOrder) => workOrder.sewing_flow_id) ? "/api/sewing-flows" : null;
  const { data: sewingFlows } = useSWR<any[]>(sewingFlowKey, fetcher);
  const processKey = useMemo(() => {
    if (!data?.length) return null;
    const orderIds = [...new Set(data.map((workOrder) => Number(workOrder.production_order_id)).filter(Boolean))];
    const params = new URLSearchParams({ page_size: String(orderIds.length) });
    for (const id of orderIds) params.append("production_order_ids", String(id));
    return `/api/process-tracking?${params.toString()}`;
  }, [data]);
  const { data: processes } = useSWR<any[]>(processKey, fetcher);
  const processByPo = new Map((processes || []).map((p) => [p.production_order_id, p]));
  const sewingFlowById = new Map((sewingFlows || []).map((flow) => [flow.id, flow]));

  return (
    <div>
      <PageHeader title={t("page.wo.title")} subtitle={t("page.wo.subtitle")} />
      <div className="card mb-4 flex items-center gap-3 p-3">
        <span className="text-sm text-slate-500">{t("page.wo.filter")}</span>
        <select className="input max-w-xs" value={dept} onChange={(e) => { setDept(e.target.value); setPage(1); }}>
          <option value="">{t("page.wo.all")}</option>
          {depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.orderNo")}</th>
              <th>{t("field.operation")}</th>
              <th>{t("common.status")}</th>
              <th>{t("page.wo.pipeline")}</th>
              <th>{t("field.input")}</th>
              <th>{t("field.output")}</th>
              <th>{t("field.failed")}</th>
              <th>{t("field.deadline")}</th>
              <th>{t("field.line")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((w) => (
              <tr key={w.id}>
                <td>
                  <Link href={`/production-orders/${w.production_order_id}`} className="font-medium text-brand-600 hover:underline">
                    {orderReference(w, `#${w.production_order_id}`)}
                  </Link>
                </td>
                <td>{operationLabel(w.operation, t)}</td>
                <td><span className="badge">{statusLabel(w.status, t)}</span></td>
                <td>
                  <StagePipeline
                    currentStage={processByPo.get(w.production_order_id)?.current_stage}
                    stages={processByPo.get(w.production_order_id)?.stages}
                  />
                </td>
                <td>{w.actual_input_qty}</td>
                <td>{w.actual_output_qty}</td>
                <td>{w.failed_qty}</td>
                <td>{w.deadline ? new Date(w.deadline).toLocaleDateString() : "—"}</td>
                <td>
                  {w.sewing_flow_id
                    ? sewingFlowById.get(w.sewing_flow_id)?.name || `#${w.sewing_flow_id}`
                    : "—"}
                </td>
                <td>
                  {w.operation === "cutting" && <Link href={`/work-orders/${w.id}/cutting`} className="text-brand-600 hover:underline">{t("dash.cutting")}</Link>}
                  {w.operation === "printing" && <Link href={`/work-orders/${w.id}/printing`} className="text-brand-600 hover:underline">{t("dash.printing")}</Link>}
                  {w.operation === "sewing" && <Link href={`/work-orders/${w.id}/sewing`} className="text-brand-600 hover:underline">{t("dash.sewing")}</Link>}
                  {w.operation === "packaging" && <Link href={`/work-orders/${w.id}/packaging`} className="text-brand-600 hover:underline">{t("dash.packaging")}</Link>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={workOrderPage?.total ?? 0}
          count={data?.length ?? 0}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
          pageSizeOptions={[25, 50, 100]}
        />
      </div>
    </div>
  );
}
