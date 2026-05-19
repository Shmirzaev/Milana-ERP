"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
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
  const { data: wo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(po?.model_id ? `/api/models/${po.model_id}` : null, fetcher);
  const { data: flows = [] } = useSWR<Flow[]>("/api/sewing-flows", fetcher);
  const { data: assignments = [], mutate: mutateAssignments } = useSWR<Assignment[]>(wo ? `/api/work-orders/${id}/assignments` : null, fetcher);
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
    input_qty: number;
    sewn_qty: number;
    passed_qty: number;
    failed_qty: number;
    rework_qty: number;
    rejected_qty: number;
    line_name: string;
    sewing_assignment_id: number | null;
    defect_reason: string;
    notes: string;
  }>({
    input_qty: 0,
    sewn_qty: 0,
    passed_qty: 0,
    failed_qty: 0,
    rework_qty: 0,
    rejected_qty: 0,
    line_name: "",
    sewing_assignment_id: null,
    defect_reason: "",
    notes: "",
  });
  const [msg, setMsg] = useState("");
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/sewing/records", { work_order_id: id, ...f });
      mutateAssignments();
      setF((prev) => ({
        ...prev,
        input_qty: 0,
        sewn_qty: 0,
        passed_qty: 0,
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

  function d(v?: string | null) {
    return v ? new Date(v).toLocaleDateString() : "-";
  }

  return (
    <div>
      <PageHeader title={t("page.sewing.title", { id })} subtitle={t("page.sewing.subtitle")} />
      <div className="card mb-4 p-4">
        <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.shipments.salesOrder")}</div>
            <div className="font-medium">{so?.order_no || (po?.sales_order_id ? `#${po.sales_order_id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.customer")}</div>
            <div className="font-medium">{so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : "-"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.model")}</div>
            <div className="font-medium">{model ? `${model.code} - ${model.name}` : (po?.model_id ? `#${po.model_id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.productionOrder")}</div>
            <div className="font-medium">{po?.production_no || (po?.id ? `#${po.id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.plannedQty")}</div>
            <div className="font-medium">{po?.planned_quantity ?? wo?.planned_output_qty ?? 0}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("common.status")}</div>
            <div className="font-medium">{wo?.status || "-"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.salesDeadline")}</div>
            <div className="font-medium">{d(so?.deadline)}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.poDeadline")}</div>
            <div className="font-medium">{d(po?.deadline)}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.woDeadline")}</div>
            <div className="font-medium">{d(wo?.deadline)}</div>
          </div>
        </div>
        {Array.isArray(po?.items) && po.items.length > 0 && (
          <div className="mt-3 border-t border-[#ecebe3] pt-3">
            <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.breakdown")}</div>
            <div className="flex flex-wrap gap-2">
              {po.items.map((it: any) => (
                <span key={it.id} className="rounded-full bg-[#f5f2e8] px-3 py-1 text-xs text-[#5d5747]">
                  {(it.color || "-")} / {(it.size || "-")} / {it.planned_quantity ?? 0}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      <form onSubmit={submit} className="card max-w-2xl space-y-3 p-6">
        <div>
          <label className="label">{t("field.inputQty")}</label>
          <input className="input" type="number" value={f.input_qty} onChange={(e) => setF({ ...f, input_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.output")}</label>
          <input className="input" type="number" value={f.sewn_qty} onChange={(e) => setF({ ...f, sewn_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.passed")}</label>
          <input className="input" type="number" value={f.passed_qty} onChange={(e) => setF({ ...f, passed_qty: Number(e.target.value) })} />
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
