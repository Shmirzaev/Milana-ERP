"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function WorkOrdersPage() {
  const { t } = useT();
  const [dept, setDept] = useState<string>("");
  const url = dept ? `/api/work-orders?department_id=${dept}` : "/api/work-orders";
  const { data } = useSWR<any[]>(url, fetcher);
  const { data: depts } = useSWR<any[]>("/api/departments", fetcher);

  function opLabel(op: string) {
    if (op === "cutting") return t("dash.cutting");
    if (op === "printing") return t("dash.printing");
    if (op === "sewing") return t("dash.sewing");
    if (op === "packaging") return t("dash.packaging");
    return op;
  }

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
              <th>{t("field.id")}</th>
              <th>{t("field.operation")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.input")}</th>
              <th>{t("field.output")}</th>
              <th>{t("field.passed")}</th>
              <th>{t("field.failed")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((w) => (
              <tr key={w.id}>
                <td>{w.id}</td>
                <td>{opLabel(w.operation)}</td>
                <td><span className="badge">{w.status}</span></td>
                <td>{w.actual_input_qty}</td>
                <td>{w.actual_output_qty}</td>
                <td>{w.passed_qty}</td>
                <td>{w.failed_qty}</td>
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
