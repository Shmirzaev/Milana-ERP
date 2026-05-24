"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel, formatBatchSerial } from "@/lib/batchSerial";
import { statusLabel } from "@/components/StagePipeline";
import PageHeader from "@/components/PageHeader";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type PrintingAttachment = { file_url: string; file_name?: string | null; content_type?: string | null };

export default function PrintingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { me } = useMe();
  const canCollect = can(me, "*", "printing.records", "planning.production");
  const [f, setF] = useState({
    production_batch_id: 0,
    input_qty: 0,
    printed_qty: 0,
    rejected_qty: 0,
    defect_reason: "",
    print_type: "",
    notes: "",
  });
  const [msg, setMsg] = useState("");
  const [collectBusy, setCollectBusy] = useState(false);
  const [collect, setCollect] = useState({ deadline: "", notes: "" });
  const { data: wo, mutate: mutateWo } = useSWR<any>(Number.isFinite(id) ? `/api/work-orders/${id}` : null, fetcher);
  const { data: po } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: batchProgress, mutate: mutateBatchProgress } = useSWR<any>(
    wo ? `/api/work-orders/${id}/printing-batch-progress` : null,
    fetcher,
  );
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: customers } = useSWR<any[]>(so?.customer_id ? "/api/customers" : null, fetcher);
  const { data: models } = useSWR<any[]>((so?.items?.length ?? 0) > 0 ? "/api/models" : null, fetcher);
  const printFiles: PrintingAttachment[] = Array.isArray(so?.printing_attachments) ? so.printing_attachments : [];
  const customerName = customers?.find((c) => Number(c.id) === Number(so?.customer_id))?.name;
  const soItems = Array.isArray(so?.items) ? so.items : [];
  const printingItems = soItems.filter((item: any) => Boolean(item?.printing_required));
  const orderItemsForPrint = printingItems.length > 0 ? printingItems : soItems;
  const woStatus = String(wo?.status || "").toLowerCase();
  const needsCollection = ["new", "planning", "waiting", "ready", "pending", "paused"].includes(woStatus);
  const canCollectNow = canCollect && ["new", "planning", "waiting", "ready", "pending", "paused", "collected"].includes(woStatus);
  const canRecordNow = woStatus === "in_progress";
  const isAlreadyBatched = Array.isArray(po?.batches) && po.batches.length > 0;
  const batchItems = Array.isArray(batchProgress?.items) ? batchProgress.items : [];

  useEffect(() => {
    if (!wo?.deadline || collect.deadline) return;
    setCollect((prev) => ({ ...prev, deadline: String(wo.deadline).slice(0, 10) }));
  }, [wo?.deadline, collect.deadline]);

  useEffect(() => {
    if (!isAlreadyBatched || !Array.isArray(po?.batches) || po.batches.length === 0) return;
    setF((prev) => {
      if (prev.production_batch_id) return prev;
      return { ...prev, production_batch_id: Number(po.batches[0].id || 0) };
    });
  }, [isAlreadyBatched, po?.batches]);

  function isImageAttachment(a: PrintingAttachment): boolean {
    const byMime = (a.content_type || "").toLowerCase().startsWith("image/");
    const byName = /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(a.file_name || a.file_url || "");
    return byMime || byName;
  }

  function modelLabel(modelId: number): string {
    const m = models?.find((row: any) => Number(row.id) === Number(modelId));
    return m ? `${m.code} - ${m.name}` : String(modelId || "—");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (isAlreadyBatched && !f.production_batch_id) {
      setMsg("Select a batch before saving the printing record.");
      return;
    }
    try {
      const outputQty = Math.max(0, Number(f.printed_qty || 0));
      await api.post("/api/printing/records", {
        work_order_id: id,
        ...f,
        passed_qty: outputQty,
        production_batch_id: f.production_batch_id || null,
      });
      mutateWo();
      mutateBatchProgress();
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  async function collectForPlan(e: React.FormEvent) {
    e.preventDefault();
    if (!collect.deadline) return;
    setCollectBusy(true);
    setMsg("");
    try {
      await api.post(`/api/work-orders/${id}/collect`, {
        deadline: new Date(collect.deadline).toISOString(),
        notes: collect.notes.trim() ? collect.notes.trim() : null,
      });
      await mutateWo();
      setMsg(t("msg.printingCollected"));
    } catch (e: any) {
      setMsg(e.message);
    } finally {
      setCollectBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.printing.title", { id })} />
      {wo && (
        <div className="card mb-4 max-w-2xl space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="text-sm font-medium">{t("common.status")}: <span className="badge">{statusLabel(wo.status, t)}</span></div>
            <div className="text-sm text-[#8a8472]">{t("field.deadline")}: {wo.deadline ? new Date(wo.deadline).toLocaleDateString() : "—"}</div>
          </div>
          {needsCollection && <div className="text-sm text-amber-700">{t("msg.printingNeedsCollect")}</div>}
          {canCollectNow && (
            <form className="grid gap-3 sm:grid-cols-2" onSubmit={collectForPlan}>
              <div className="sm:col-span-2">
                <div className="label">{t("page.printing.collectForPlan")}</div>
                <div className="text-xs text-[#8a8472]">{t("page.printing.collectHint")}</div>
              </div>
              <div>
                <label className="label">{t("field.deadline")}</label>
                <input className="input" type="date" value={collect.deadline} onChange={(e) => setCollect({ ...collect, deadline: e.target.value })} required />
              </div>
              <div>
                <label className="label">{t("common.notes")}</label>
                <input className="input" value={collect.notes} onChange={(e) => setCollect({ ...collect, notes: e.target.value })} />
              </div>
              <div className="sm:col-span-2">
                <button className="btn" disabled={collectBusy || !collect.deadline}>
                  {collectBusy ? t("common.loading") : t("btn.collect")}
                </button>
              </div>
            </form>
          )}
        </div>
      )}
      {so && (
        <div className="card mb-4 max-w-2xl space-y-3 p-4">
          <div className="label">{t("newso.orderDetails")}</div>
          <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
            <div className="flex justify-between gap-3 rounded-md bg-[#f8f7f3] px-3 py-2"><dt className="text-[#8a8472]">{t("field.orderNo")}</dt><dd className="font-medium">{so.order_no || "—"}</dd></div>
            <div className="flex justify-between gap-3 rounded-md bg-[#f8f7f3] px-3 py-2"><dt className="text-[#8a8472]">{t("field.productionNo")}</dt><dd className="font-medium">{po?.production_no || "—"}</dd></div>
            <div className="flex justify-between gap-3 rounded-md bg-[#f8f7f3] px-3 py-2"><dt className="text-[#8a8472]">{t("field.customer")}</dt><dd className="font-medium">{customerName || so.customer_id || "—"}</dd></div>
            <div className="flex justify-between gap-3 rounded-md bg-[#f8f7f3] px-3 py-2"><dt className="text-[#8a8472]">{t("field.deadline")}</dt><dd className="font-medium">{so.deadline ? new Date(so.deadline).toLocaleDateString() : "—"}</dd></div>
            <div className="flex justify-between gap-3 rounded-md bg-[#f8f7f3] px-3 py-2 sm:col-span-2"><dt className="text-[#8a8472]">{t("field.plannedQty")}</dt><dd className="font-medium">{wo?.planned_output_qty ?? po?.planned_quantity ?? "—"}</dd></div>
          </dl>
          {orderItemsForPrint.length > 0 && (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("field.model")}</th>
                    <th>{t("field.color")}</th>
                    <th>{t("field.size")}</th>
                    <th>{t("field.qty")}</th>
                  </tr>
                </thead>
                <tbody>
                  {orderItemsForPrint.map((item: any) => (
                    <tr key={item.id}>
                      <td>{modelLabel(Number(item.model_id))}</td>
                      <td>{item.color || "—"}</td>
                      <td>{item.size || "—"}</td>
                      <td>{item.quantity ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {so?.notes && (
            <div>
              <div className="label">{t("field.notes")}</div>
              <div className="rounded-md bg-[#f8f7f3] p-3 text-sm whitespace-pre-wrap">{so.notes}</div>
            </div>
          )}
        </div>
      )}
      {(so?.printing_instructions || printFiles.length > 0) && (
        <div className="card mb-4 max-w-2xl space-y-3 p-4">
          <div>
            <div className="label">Printing details</div>
            <div className="mt-1 text-sm text-[#8a8472]">
              Sales order {so?.order_no || ""} instructions for print execution.
            </div>
          </div>
          {so?.printing_instructions && (
            <div className="rounded-md bg-[#f8f7f3] p-3 text-sm whitespace-pre-wrap">
              {so.printing_instructions}
            </div>
          )}
          {printFiles.length > 0 && (
            <div className="space-y-2">
              {printFiles.map((file, idx) => (
                <div key={`${file.file_url}-${idx}`} className="flex flex-wrap items-center gap-3 rounded-md border border-[#ecebe3] p-2">
                  {isImageAttachment(file) && <img src={file.file_url} alt={file.file_name || "print"} className="h-12 w-12 rounded object-cover" />}
                  <a className="text-sm text-[#3b3528] underline" href={file.file_url} target="_blank" rel="noreferrer">
                    {file.file_name || file.file_url}
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {isAlreadyBatched && (
        <div className="card mb-4 p-4">
          <div className="mb-2 text-base font-semibold">Batches Managed Inside This Work Order</div>
          <div className="mb-3 text-sm text-slate-600">
            Record each printing action against a batch below. This order stays as one WO.
          </div>
          <div className="overflow-x-auto">
            <table className="table text-sm">
              <thead>
                <tr>
                  <th>Batch</th>
                  <th>Planned</th>
                  <th>Output</th>
                  <th>Rejected</th>
                  <th>Remaining</th>
                  <th>Progress</th>
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
                    <td>{row.rejected_qty}</td>
                    <td>{row.remaining_quantity}</td>
                    <td>{row.progress_pct}%</td>
                  </tr>
                ))}
                {batchItems.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-slate-500">No batch progress yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {canRecordNow ? (
        <form onSubmit={submit} className="card max-w-2xl space-y-3 p-6">
          {isAlreadyBatched && (
            <div>
              <label className="label">Order batch</label>
              <select
                className="input"
                value={f.production_batch_id}
                onChange={(e) => setF({ ...f, production_batch_id: Number(e.target.value) })}
              >
                <option value={0}>Select batch</option>
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
            <input className="input" type="number" value={f.printed_qty} onChange={(e) => setF({ ...f, printed_qty: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.rejected")}</label>
            <input className="input" type="number" value={f.rejected_qty} onChange={(e) => setF({ ...f, rejected_qty: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.printType")}</label>
            <input className="input" value={f.print_type} onChange={(e) => setF({ ...f, print_type: e.target.value })} />
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
      ) : (
        <div className="card max-w-2xl p-4 text-sm text-[#8a8472]">{t("msg.printingInputLockedUntilInProgress")}</div>
      )}
    </div>
  );
}
