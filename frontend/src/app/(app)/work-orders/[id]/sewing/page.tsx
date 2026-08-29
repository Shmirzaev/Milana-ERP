"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel, formatBatchSerial } from "@/lib/batchSerial";
import PageHeader from "@/components/PageHeader";
import DefectReasonSelect from "@/components/DefectReasonSelect";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import WorkOrderProductInfo from "@/components/WorkOrderProductInfo";
import { useT } from "@/lib/i18n";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import { orderReference } from "@/lib/orderRef";

type Flow = {
  id: number;
  code: string;
  name: string;
};

type Assignment = {
  id: number;
  production_batch_id: number | null;
  sewing_flow_id: number;
  quantity: number;
  completed_qty: number;
};

type LineOption = {
  key: string;
  assignmentId: number | null;
  productionBatchId: number | null;
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
  const { data: replacementStatus, mutate: mutateReplacementStatus } = useSWR<any>(
    wo ? `/api/work-orders/${id}/replacement-status` : null,
    fetcher,
  );
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);
  const batchById = useMemo(() => new Map((po?.batches || []).map((b: any) => [Number(b.id), b])), [po?.batches]);
  const lineOptions = useMemo<LineOption[]>(() => {
    if (assignments.length > 0) {
      return assignments.map((a) => {
        const flow = flows.find((f) => f.id === a.sewing_flow_id);
        const lineName = flow?.name || flow?.code || `#${a.sewing_flow_id}`;
        const remaining = Math.max(0, Number(a.quantity || 0) - Number(a.completed_qty || 0));
        const batchId = Number(a.production_batch_id || 0) || null;
        const batch = batchId ? batchById.get(batchId) : null;
        const batchLabel = batch ? ` - ${formatBatchLabel(batch, po?.id)}` : "";
        return {
          key: `assignment:${a.id}`,
          assignmentId: a.id,
          productionBatchId: batchId,
          lineName,
          label: `${lineName}${flow?.code ? ` (${flow.code})` : ""}${batchLabel} (${remaining}/${a.quantity})`,
          disabled: false,
        };
      });
    }
    if (wo?.sewing_flow_id) {
      const flow = flows.find((f) => f.id === wo.sewing_flow_id);
      const lineName = flow?.name || flow?.code || `#${wo.sewing_flow_id}`;
      return [{
        key: `flow:${wo.sewing_flow_id}`,
        assignmentId: null,
        productionBatchId: null,
        lineName,
        label: `${lineName}${flow?.code ? ` (${flow.code})` : ""}`,
        disabled: false,
      }];
    }
    if (flows.length > 0) {
      return flows.map((flow) => ({
        key: `flow:${flow.id}`,
        assignmentId: null,
        productionBatchId: null,
        lineName: flow.name || flow.code || `#${flow.id}`,
        label: `${flow.name || flow.code || `#${flow.id}`}${flow.code ? ` (${flow.code})` : ""}`,
        disabled: false,
      }));
    }
    return [];
  }, [assignments, batchById, flows, po?.id, wo?.sewing_flow_id]);
  const [f, setF] = useState<{
    production_batch_id: number;
    input_qty: NumberInputValue;
    sewn_qty: NumberInputValue;
    failed_qty: NumberInputValue;
    line_name: string;
    sewing_assignment_id: number | null;
    defect_reason: string;
    notes: string;
  }>({
    production_batch_id: 0,
    input_qty: "",
    sewn_qty: "",
    failed_qty: "",
    line_name: "",
    sewing_assignment_id: null,
    defect_reason: "",
    notes: "",
  });
  const [msg, setMsg] = useState("");
  const [replacementCompletion, setReplacementCompletion] = useState<{
    production_batch_id: number;
    completed_pieces: NumberInputValue;
    line_key: string;
  }>({ production_batch_id: 0, completed_pieces: "", line_key: "" });
  const [replacementCompletionBusy, setReplacementCompletionBusy] = useState(false);
  const [replacementCompletionErr, setReplacementCompletionErr] = useState("");
  const [replacementCompletionDone, setReplacementCompletionDone] = useState("");
  const isAlreadyBatched = Array.isArray(po?.batches) && po.batches.length > 0;
  const batchItems = Array.isArray(batchProgress?.items) ? batchProgress.items : [];
  const selectedLine = useMemo(
    () => lineOptions.find((opt) => opt.assignmentId === f.sewing_assignment_id && opt.lineName === f.line_name),
    [lineOptions, f.line_name, f.sewing_assignment_id],
  );
  const pendingReplacementItems = useMemo(
    () => (Array.isArray(replacementStatus?.items) ? replacementStatus.items : [])
      .filter((row: any) => Number(row?.waiting_sewing_qty || 0) > 0),
    [replacementStatus?.items],
  );
  const selectedReplacementItem = useMemo(
    () => pendingReplacementItems.find(
      (row: any) => Number(row?.production_batch_id || 0) === Number(replacementCompletion.production_batch_id || 0),
    ) || pendingReplacementItems[0] || null,
    [pendingReplacementItems, replacementCompletion.production_batch_id],
  );
  const replacementLineOptions = useMemo(() => {
    if (!selectedReplacementItem) return lineOptions;
    const batchId = Number(selectedReplacementItem.production_batch_id || 0);
    const batchLines = lineOptions.filter((option) => Number(option.productionBatchId || 0) === batchId);
    return batchLines.length > 0 ? batchLines : lineOptions;
  }, [lineOptions, selectedReplacementItem]);
  const selectedReplacementLine = useMemo(
    () => replacementLineOptions.find((option) => option.key === replacementCompletion.line_key)
      || replacementLineOptions[0]
      || null,
    [replacementCompletion.line_key, replacementLineOptions],
  );

  useEffect(() => {
    if (!lineOptions.length) return;
    const current = lineOptions.find((opt) => opt.assignmentId === f.sewing_assignment_id && opt.lineName === f.line_name);
    if (current) return;
    const next = lineOptions.find((opt) => !opt.disabled) || lineOptions[0];
    setF((prev) => ({
      ...prev,
      line_name: next.lineName,
      sewing_assignment_id: next.assignmentId,
      production_batch_id: next.productionBatchId || prev.production_batch_id,
    }));
  }, [lineOptions, f.sewing_assignment_id, f.line_name]);

  useEffect(() => {
    if (!selectedLine?.productionBatchId) return;
    setF((prev) => (
      prev.production_batch_id === selectedLine.productionBatchId
        ? prev
        : { ...prev, production_batch_id: selectedLine.productionBatchId || 0 }
    ));
  }, [selectedLine?.productionBatchId]);

  useEffect(() => {
    if (!isAlreadyBatched || !Array.isArray(po?.batches) || po.batches.length === 0) return;
    setF((prev) => {
      if (prev.production_batch_id) return prev;
      return { ...prev, production_batch_id: Number(po.batches[0].id || 0) };
    });
  }, [isAlreadyBatched, po?.batches]);

  useEffect(() => {
    if (pendingReplacementItems.length === 0) return;
    setReplacementCompletion((prev) => {
      const selected = pendingReplacementItems.find(
        (row: any) => Number(row?.production_batch_id || 0) === Number(prev.production_batch_id || 0),
      ) || pendingReplacementItems[0];
      const nextBatchId = Number(selected?.production_batch_id || 0);
      if (nextBatchId === Number(prev.production_batch_id || 0) && numberOrZero(prev.completed_pieces) > 0) return prev;
      return {
        ...prev,
        production_batch_id: nextBatchId,
        completed_pieces: Number(selected?.waiting_sewing_qty || 0),
      };
    });
  }, [pendingReplacementItems]);

  useEffect(() => {
    if (replacementLineOptions.length === 0) return;
    setReplacementCompletion((prev) => (
      replacementLineOptions.some((option) => option.key === prev.line_key)
        ? prev
        : { ...prev, line_key: replacementLineOptions[0].key }
    ));
  }, [replacementLineOptions]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (isAlreadyBatched && !f.production_batch_id) {
      setMsg(t("batch.selectBeforeSaving", { operation: operationLabel("sewing", t).toLowerCase() }));
      return;
    }
    try {
      const failedQty = Math.max(0, numberOrZero(f.failed_qty));
      const outputQty = Math.max(0, numberOrZero(f.sewn_qty));
      await api.post("/api/sewing/records", {
        work_order_id: id,
        ...f,
        input_qty: numberOrZero(f.input_qty),
        sewn_qty: outputQty,
        failed_qty: failedQty,
        rework_qty: 0,
        rejected_qty: 0,
        passed_qty: outputQty,
        production_batch_id: selectedLine?.productionBatchId || f.production_batch_id || null,
      });
      mutateAssignments();
      mutateBatchProgress();
      mutateWo();
      mutateReplacementStatus();
      setF((prev) => ({
        ...prev,
        input_qty: "",
        sewn_qty: "",
        failed_qty: "",
        defect_reason: "",
        notes: "",
      }));
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  async function completeReplacementSewing() {
    const completedPieces = numberOrZero(replacementCompletion.completed_pieces);
    const waitingPieces = Math.max(0, Number(selectedReplacementItem?.waiting_sewing_qty || 0));
    setReplacementCompletionErr("");
    setReplacementCompletionDone("");
    if (!selectedReplacementItem || completedPieces <= 0 || completedPieces > waitingPieces) {
      setReplacementCompletionErr(t("replacement.invalidCompletedQty", { count: waitingPieces.toLocaleString() }));
      return;
    }

    setReplacementCompletionBusy(true);
    try {
      const result = await api.post("/api/sewing/records", {
        work_order_id: id,
        production_batch_id: selectedReplacementItem.production_batch_id || null,
        input_qty: completedPieces,
        sewn_qty: completedPieces,
        passed_qty: completedPieces,
        failed_qty: 0,
        rework_qty: 0,
        rejected_qty: 0,
        line_name: selectedReplacementLine?.lineName || "Replacement",
        sewing_assignment_id: selectedReplacementLine?.assignmentId ?? null,
        notes: "Replacement sewing completed",
      });
      const recorded = Math.max(0, Number(result?.replacement_completed_qty || 0));
      setReplacementCompletionDone(t("replacement.sewingCompleted", { count: recorded.toLocaleString() }));
      setReplacementCompletion((prev) => ({ ...prev, completed_pieces: "" }));
      await Promise.all([mutateAssignments(), mutateBatchProgress(), mutateWo(), mutateReplacementStatus()]);
    } catch (e: any) {
      setReplacementCompletionErr(e?.message || t("replacement.sewingCompleteFailed"));
    } finally {
      setReplacementCompletionBusy(false);
    }
  }

  const orderNo = orderReference({
    order_no: so?.order_no || po?.order_no || wo?.order_no,
    sales_order_no: po?.sales_order_no || wo?.sales_order_no,
    production_no: po?.production_no || wo?.production_no,
    production_order_id: wo?.production_order_id,
  }, `#${id}`);

  return (
    <div>
      <PageHeader title={t("page.sewing.title", { id, orderNo })} subtitle={t("page.sewing.subtitle")} />
      <WorkOrderProductInfo
        t={t}
        so={so}
        po={po}
        wo={wo}
        model={model}
        customerName={so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : null}
        statusText={wo ? statusLabel(wo.status, t) : "-"}
      />
      {Number(replacementStatus?.open_qty || 0) > 0 && (
        <>
          <div className={`${pendingReplacementItems.length > 0 ? "" : "mb-4"} border-y border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950`}>
            <div className="font-semibold">
              {t("replacement.sewingOpen", { count: Number(replacementStatus.open_qty).toLocaleString() })}
            </div>
            <div className="mt-1 text-amber-900">
              {t("replacement.sewingBreakdown", {
                cutting: Number(replacementStatus.waiting_cutting_qty || 0).toLocaleString(),
                sewing: Number(replacementStatus.waiting_sewing_qty || 0).toLocaleString(),
              })}
            </div>
          </div>
          {pendingReplacementItems.length > 0 && (
            <section className="card mb-4 rounded-t-none border-t-0 p-4">
              <div className="mb-3">
                <h2 className="text-base font-semibold">{t("replacement.completeSewingTitle")}</h2>
                <p className="mt-1 text-sm text-slate-600">{t("replacement.completeSewingHint")}</p>
              </div>
              <div className="grid grid-cols-1 items-end gap-3 md:grid-cols-3">
                {pendingReplacementItems.length > 1 && (
                  <div>
                    <label className="label">{t("batch.orderBatch")}</label>
                    <select
                      className="input"
                      value={replacementCompletion.production_batch_id}
                      onChange={(e) => {
                        const batchId = Number(e.target.value || 0);
                        const row = pendingReplacementItems.find((item: any) => Number(item?.production_batch_id || 0) === batchId);
                        setReplacementCompletion((prev) => ({
                          ...prev,
                          production_batch_id: batchId,
                          completed_pieces: Number(row?.waiting_sewing_qty || 0),
                        }));
                      }}
                    >
                      {pendingReplacementItems.map((row: any) => (
                        <option key={row.production_batch_id || "order"} value={Number(row.production_batch_id || 0)}>
                          {row.batch_no || t("field.batch")} ({Number(row.waiting_sewing_qty || 0).toLocaleString()})
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {replacementLineOptions.length > 0 && (
                  <div>
                    <label className="label">{t("field.lineName")}</label>
                    <select
                      className="input"
                      value={selectedReplacementLine?.key || ""}
                      onChange={(e) => setReplacementCompletion((prev) => ({ ...prev, line_key: e.target.value }))}
                    >
                      {replacementLineOptions.map((option) => (
                        <option key={option.key} value={option.key}>{option.label}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div>
                  <label className="label">{t("replacement.completedPieces")}</label>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    max={Math.max(1, Number(selectedReplacementItem?.waiting_sewing_qty || 1))}
                    value={replacementCompletion.completed_pieces}
                    onChange={(e) => setReplacementCompletion((prev) => ({ ...prev, completed_pieces: parseNumberInput(e.target.value) }))}
                  />
                </div>
              </div>
              {replacementCompletionErr && <div className="mt-3 text-sm text-red-600">{replacementCompletionErr}</div>}
              <div className="mt-3">
                <button type="button" className="btn btn-primary" onClick={completeReplacementSewing} disabled={replacementCompletionBusy}>
                  {replacementCompletionBusy ? t("common.saving") : t("replacement.markSewingDone")}
                </button>
              </div>
            </section>
          )}
        </>
      )}
      {replacementCompletionDone && (
        <div className="mb-4 border-y border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          {replacementCompletionDone}
        </div>
      )}
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
                  <th>{t("replacement.waiting")}</th>
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
                    <td>{row.waiting_replacement_qty || 0}</td>
                    <td>{row.remaining_quantity}</td>
                    <td>{row.progress_pct}%</td>
                  </tr>
                ))}
                {batchItems.length === 0 && (
                  <tr>
                  <td colSpan={7} className="text-slate-500">{t("batch.noProgressYet")}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <form onSubmit={submit} className="card max-w-4xl space-y-3 p-6">
        {isAlreadyBatched && (
          <div>
            <label className="label">{t("batch.orderBatch")}</label>
            <select
              className="input"
              value={f.production_batch_id}
              disabled={!!selectedLine?.productionBatchId}
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
          <input className="input" type="number" value={f.input_qty} onChange={(e) => setF({ ...f, input_qty: parseNumberInput(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.output")}</label>
          <input className="input" type="number" value={f.sewn_qty} onChange={(e) => setF({ ...f, sewn_qty: parseNumberInput(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.failed")}</label>
          <input className="input" type="number" value={f.failed_qty} onChange={(e) => setF({ ...f, failed_qty: parseNumberInput(e.target.value) })} />
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
                production_batch_id: picked?.productionBatchId || prev.production_batch_id,
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
          <label className="label" htmlFor="sewing-defect-reason">{t("field.defectReason")}</label>
          <DefectReasonSelect
            id="sewing-defect-reason"
            value={f.defect_reason}
            onChange={(defect_reason) => setF({ ...f, defect_reason })}
            required={numberOrZero(f.failed_qty) > 0}
          />
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
