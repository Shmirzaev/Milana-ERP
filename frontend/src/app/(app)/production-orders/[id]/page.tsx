"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Link from "next/link";
import { useT } from "@/lib/i18n";

export default function ProductionOrderDetail() {
  const params = useParams<{ id: string }>();
  const { t } = useT();
  const id = params.id;
  const { data: po, mutate } = useSWR<any>(`/api/production-orders/${id}`, fetcher);

  async function createWOs() {
    await api.post(`/api/production-orders/${id}/create-work-orders?include_printing=false`);
    mutate();
  }
  async function startWO(wid: number) { await api.post(`/api/work-orders/${wid}/start`); mutate(); }
  async function completeWO(wid: number) { await api.post(`/api/work-orders/${wid}/complete`); mutate(); }

  if (!po) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader
        title={t("page.poDetail.title", { productionNo: po.production_no })}
        subtitle={t("page.poDetail.subtitle", { type: po.production_type, status: po.status })}
        actions={<button className="btn" onClick={createWOs}>{t("btn.generateWorkOrders")}</button>}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <div className="card p-4">
          <h3 className="font-medium mb-2">{t("page.poDetail.plan")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.color")}</th><th>{t("field.size")}</th>
                <th>{t("page.poDetail.planned")}</th><th>{t("page.poDetail.completed")}</th>
              </tr>
            </thead>
            <tbody>{po.items?.map((i: any) => <tr key={i.id}><td>{i.color}</td><td>{i.size}</td><td>{i.planned_quantity}</td><td>{i.completed_quantity}</td></tr>)}</tbody>
          </table>
        </div>
        <div className="card p-4">
          <h3 className="font-medium mb-2">{t("page.poDetail.summary")}</h3>
          <dl className="text-sm space-y-1">
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.model")}</dt><dd>{po.model_id}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.poDetail.salesOrder")}</dt><dd>{po.sales_order_id || "—"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.poDetail.plannedQty")}</dt><dd>{po.planned_quantity}</dd></div>
          </dl>
        </div>
      </div>

      <div className="card p-4">
        <h3 className="font-medium mb-2">{t("page.poDetail.workOrders")}</h3>
        <table className="table">
          <thead>
            <tr>
              <th>{t("page.poDetail.op")}</th><th>{t("field.dept")}</th><th>{t("field.status")}</th>
              <th>{t("field.input")}</th><th>{t("field.output")}</th>
              <th>{t("field.passed")}</th><th>{t("field.failed")}</th><th></th>
            </tr>
          </thead>
          <tbody>
            {po.work_orders?.map((w: any) => (
              <tr key={w.id}>
                <td className="font-medium">{w.operation}</td>
                <td>{w.department_id}</td>
                <td><span className="badge">{w.status}</span></td>
                <td>{w.actual_input_qty}</td>
                <td>{w.actual_output_qty}</td>
                <td>{w.passed_qty}</td>
                <td>{w.failed_qty}</td>
                <td className="flex gap-2 flex-wrap">
                  {w.status === "waiting" && <button className="text-brand-600 hover:underline" onClick={() => startWO(w.id)}>{t("btn.start")}</button>}
                  {w.status === "in_progress" && <button className="text-green-700 hover:underline" onClick={() => completeWO(w.id)}>{t("btn.complete")}</button>}
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
