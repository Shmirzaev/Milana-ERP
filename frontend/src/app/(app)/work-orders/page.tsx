"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import StagePipeline, { operationLabel, statusLabel } from "@/components/StagePipeline";
import { orderReference } from "@/lib/orderRef";

export default function WorkOrdersPage() {
  const { t } = useT();
  const searchParams = useSearchParams();
  // Allow ?dept=CUT|PRT|SEW|PKG|FGS to pre-filter from the sidebar.
  const deptCode = searchParams?.get("dept") ?? "";
  const { data: depts } = useSWR<any[]>("/api/departments", fetcher);
  const [dept, setDept] = useState<string>("");

  // Once departments arrive, translate code → id (only if URL had a code).
  useEffect(() => {
    if (!deptCode || !depts) return;
    const match = depts.find((d) => d.code === deptCode);
    if (match) setDept(String(match.id));
  }, [deptCode, depts]);

  const url = dept ? `/api/work-orders?department_id=${dept}` : "/api/work-orders";
  const { data } = useSWR<any[]>(url, fetcher);
  const { data: processes } = useSWR<any[]>("/api/process-tracking", fetcher);
  const processByPo = new Map((processes || []).map((p) => [p.production_order_id, p]));

  return (
    <div>
      <PageHeader title={t("page.wo.title")} subtitle={t("page.wo.subtitle")} />
      <div className="card mb-4 flex items-center gap-3 p-3">
        <span className="text-sm text-slate-500">{t("page.wo.filter")}</span>
        <select className="input max-w-xs" value={dept} onChange={(e) => setDept(e.target.value)}>
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
                <td>{w.sewing_flow_id ?? "—"}</td>
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
      </div>
    </div>
  );
}
