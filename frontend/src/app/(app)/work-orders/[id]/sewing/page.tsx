"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel, formatBatchSerial } from "@/lib/batchSerial";
import PageHeader from "@/components/PageHeader";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import WorkOrderProductInfo from "@/components/WorkOrderProductInfo";
import { useT } from "@/lib/i18n";

type Flow = {
  id: number;
  code: string;
  name: string;
};

type Assignment = {
  id: number;
  sewing_flow_id: number;
  quantity: number;
  completed_qty: number;
};

type LineOption = {
  key: string;
  assignmentId: number | null;
  lineName: string;
  label: string;
  disabled: boolean;
};

export default function SewingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data: wo, mutate: mutateWo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(po?.model_id ? `/api/models/${po.model_id}` : null, fetcher);
  const { data: flows = [] } = useSWR<Flow[]>("/api/sewing-flows", fetcher);
  const { data: assignments = [], mutate: mutateAssignments } = useSWR<Assignment[]>(wo ? `/api/work-orders/${id}/assignments` : null, fetcher);
  const { data: batchProgress, mutate: mutateBatchProgress } = useSWR<any>(
    wo ? `/api/work-orders/${id}/sewing-batch-progress` : null,
    fetcher,
  );
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);
  const lineOptions = useMemo<LineOption[]>(() => {
    if (assignments.length > 0) {
      return assignments.map((a) => {
        const flow = flows.find((f) => f.id === a.sewing_flow_id);
        const lineName = flow?.code || flow?.name || `#${a.sewing_flow_id}`;
        const remaining = Math.max(0, Number(a.quantity || 0) - Number(a.completed_qty || 0));
        return {
          key: `assignment:${a.id}`,
          assignmentId: a.id,
          lineName,
          label: `${lineName}${flow?.name ? ` - ${flow.name}` : ""} (${remaining}/${a.quantity})`,
          disabled: false,
        };
      });
    }
    if (wo?.sewing_flow_id) {
      const flow = flows.find((f) => f.id === wo.sewing_flow_id);
      const lineName = flow?.code || flow?.name || `#${wo.sewing_flow_id}`;
      return [{
        key: `flow:${wo.sewing_flow_id}`,
        assignmentId: null,
        lineName,
        label: `${lineName}${flow?.name ? ` - ${flow.name}` : ""}`,
        disabled: false,
      }];
    }
    if (flows.length > 0) {
      return flows.map((flow) => ({
        key: `flow:${flow.id}`,
        assignmentId: null,
        lineName: flow.code || flow.name || `#${flow.id}`,
        label: `${flow.code || flow.name || `#${flow.id}`}${flow.name ? ` - ${flow.name}` : ""}`,
        disabled: false,
      }));
    }
    return [];
  }, [assignments, flows, wo?.sewing_flow_id]);
  const [f, setF] = useState<{
    production_batch_id: number;
    input_qty: number;
    sewn_qty: number;
    failed_qty: number;
    rework_qty: number;
    rejected_qty: number;
    line_name: string;
    sewing_assignment_id: number | null;
    defect_reason: string;
    notes: string;
  }>({
    production_batch_id: 0,
    input_qty: 0,
    sewn_qty: 0,
    failed_qty: 0,
    rework_qty: 0,
    rejected_qty: 0,
    line_name: "",
    sewing_assignment_id: null,
    defect_reason: "",
    notes: "",
  });
  const [msg, setMsg] = useState("");
  const isAlreadyBatched = Array.isArray(po?.batches) && po.batches.length > 0;
  const batchItems = Array.isArray(batchProgress?.items) ? batchProgress.items : [];
  const selectedLine = useMemo(
    () => lineOptions.find((opt) => opt.assignmentId === f.sewing_assignment_id && opt.lineName === f.line_name),
    [lineOptions, f.line_name, f.sewing_assignment_id],
  );

  useEffect(() => {
    if (!lineOptions.length) return;
    const current = lineOptions.find((opt) => opt.assignmentId === f.sewing_assignment_id && opt.lineName === f.line_name);
    if (current) return;
    const next = lineOptions.find((opt) => !opt.disabled) || lineOptions[0];
    setF((prev) => ({ ...prev, line_name: next.lineName, sewing_assignment_id: next.assignmentId }));
  }, [lineOptions, f.sewing_assignment_id, f.line_name]);

  useEffect(() => {
    if (!isAlreadyBatched || !Array.isArray(po?.batches) || po.batches.length === 0) return;
    setF((prev) => {
      if (prev.production_batch_id) return prev;
      return { ...prev, production_batch_id: Number(po.batches[0].id || 0) };
    });
  }, [isAlreadyBatched, po?.batches]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (isAlreadyBatched && !f.production_batch_id) {
      setMsg(t("batch.selectBeforeSaving", { operation: operationLabel("sewing", t).toLowerCase() }));
      return;
    }
    try {
      const outputQty = Math.max(0, Number(f.sewn_qty || 0));
      await api.post("/api/sewing/records", {
        work_order_id: id,
        ...f,
        passed_qty: outputQty,
        production_batch_id: f.production_batch_id || null,
      });
      mutateAssignments();
      mutateBatchProgress();
      mutateWo();
      setF((prev) => ({
        ...prev,
        input_qty: 0,
        sewn_qty: 0,
        failed_qty: 0,
        rework_qty: 0,
        rejected_qty: 0,
        defect_reason: "",
        notes: "",
      }));
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.sewing.title", { id })} subtitle={t("page.sewing.subtitle")} />
      <WorkOrderProductInfo
        t={t}
        so={so}
        po={po}
        wo={wo}
        model={model}
        customerName={so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : null}
        statusText={wo ? statusLabel(wo.status, t) : "-"}
      />
      {isAlreadyBatched && (
        <div className="card mb-4 p-4">
          <div className="mb-2 text-base font-semibold">{t("batch.managedInsideWorkOrder")}</div>
          <div className="mb-3 text-sm text-slate-600">
            {t("batch.recordAction", { operation: operationLabel("sewing", t).toLowerCase() })}
          </div>
          <div className="overflow-x-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>{t("field.batch")}</th>
                  <th>{t("statusValue.planned")}</th>
                  <th>{t("field.output")}</th>
                  <th>{t("field.failed")}</th>
                  <th>{t("field.remaining")}</th>
                  <th>{t("page.processes.progress")}</th>
                </tr>
              </thead>
              <tbody>
                {batchItems.map((row: any) => (
                  <tr key={row.id}>
                    <td>
                      <div className="font-medium">{formatBatchLabel(row, po?.id)}</div>
                      <div className="text-xs text-slate-500">{formatBatchSerial(row, po?.id)}</div>
                    </td>
                    <td>{row.planned_quantity}</td>
                    <td>{row.passed_qty}</td>
                    <td>{row.failed_qty}</td>
                    <td>{row.remaining_quantity}</td>
                    <td>{row.progress_pct}%</td>
                  </tr>
                ))}
                {batchItems.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-slate-500">{t("batch.noProgressYet")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <form onSubmit={submit} className="card max-w-2xl space-y-3 p-6">
        {isAlreadyBatched && (
          <div>
            <label className="label">{t("batch.orderBatch")}</label>
            <select
              className="input"
              value={f.production_batch_id}
              onChange={(e) => setF({ ...f, production_batch_id: Number(e.target.value) })}
            >
              <option value={0}>{t("batch.selectBatch")}</option>
              {(po?.batches || []).map((b: any) => (
                <option key={b.id} value={b.id}>
                  {formatBatchLabel(b, po?.id)} ({b.planned_quantity})
                </option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label className="label">{t("field.inputQty")}</label>
          <input className="input" type="number" value={f.input_qty} onChange={(e) => setF({ ...f, input_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.output")}</label>
          <input className="input" type="number" value={f.sewn_qty} onChange={(e) => setF({ ...f, sewn_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.failed")}</label>
          <input className="input" type="number" value={f.failed_qty} onChange={(e) => setF({ ...f, failed_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.rework")}</label>
          <input className="input" type="number" value={f.rework_qty} onChange={(e) => setF({ ...f, rework_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.rejected")}</label>
          <input className="input" type="number" value={f.rejected_qty} onChange={(e) => setF({ ...f, rejected_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.lineName")}</label>
          <select
            className="input"
            value={selectedLine?.key || ""}
            onChange={(e) => {
              const picked = lineOptions.find((opt) => opt.key === e.target.value);
              setF((prev) => ({
                ...prev,
                line_name: picked?.lineName || "",
                sewing_assignment_id: picked?.assignmentId ?? null,
              }));
            }}
            required
          >
            <option value="">{t("ph.pickLine")}</option>
            {lineOptions.map((opt) => (
              <option key={opt.key} value={opt.key} disabled={opt.disabled}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">{t("field.defectReason")}</label>
          <input className="input" value={f.defect_reason} onChange={(e) => setF({ ...f, defect_reason: e.target.value })} />
        </div>
        <div>
          <label className="label">{t("common.notes")}</label>
          <textarea className="input" rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        </div>
        <button className="btn btn-primary">{t("btn.saveRecord")}</button>
        {msg && <div className="mt-2 text-sm">{msg}</div>}
      </form>
    </div>
  );
}
