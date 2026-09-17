"use client";
import { formatBatchLabel } from "@/lib/batchSerial";
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { Pencil, Trash2 } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { useDialogs } from "@/components/DialogProvider";

type RecordRow = { id: number; production_batch_id: number | null; input_qty: number; sewn_qty: number; passed_qty: number; failed_qty: number;
  line_name: string | null; created_at: string; notes: string | null; correction_version: number;
  size_quantities: { size: string; quantity: number }[]; locked_reason: string | null };
export default function SewingRecordHistory({ workOrderId, batches = [] }: { workOrderId: number; batches?: { id: number; batch_no?: string; name?: string }[] }) {
  const { me } = useMe();
  const { t } = useT();
  const dialogs = useDialogs();
  const { mutate: refresh } = useSWRConfig();
  const permitted = can(me, "sewing.records");
  const { data, error, mutate } = useSWR<RecordRow[]>(permitted ? `/api/work-orders/${workOrderId}/sewing-records` : null, fetcher);
  const [editing, setEditing] = useState<RecordRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  async function save(row: RecordRow, remove = false) {
    if (remove && !await dialogs.ask({ title: t("sewingEdit.delete"), message: t("sewingEdit.confirm"), confirmText: t("sewingEdit.delete"), tone: "danger" })) return;
    setBusy(true); setFailure(""); setMessage("");
    try {
      if (remove) await api.del(`/api/sewing/records/${row.id}`, { expected_version: row.correction_version });
      else await api.patch(`/api/sewing/records/${row.id}`, { expected_version: row.correction_version,
        input_qty: row.input_qty, sewn_qty: row.sewn_qty, passed_qty: row.passed_qty,
        size_quantities: row.size_quantities || [], notes: row.notes });
      setEditing(null); setMessage(t(remove ? "sewingEdit.deleted" : "sewingEdit.saved"));
      await mutate();
      await refresh((key) => typeof key === "string" && key.startsWith(`/api/work-orders/${workOrderId}`));
    } catch (err) {
      const text = err instanceof Error ? err.message : "";
      const key = text.match(/sewingEdit\.\w+/)?.[0];
      setFailure(key ? t(key) : text || t("sewingEdit.failed"));
    } finally { setBusy(false); }
  }
  if (!permitted) return null;
  return <section className="card p-4 space-y-4">
    <h2 className="font-semibold">{t("sewingEdit.title")}</h2>
    <p className="text-sm text-[#6d6758]">{t("sewingEdit.hint")}</p>
    {message && <p role="status" className="text-sm">{message}</p>}
    {(failure || error) && <p role="alert" className="text-sm text-red-700">{failure || t("sewingEdit.failed")}</p>}
    {!data && !error && <p>{t("common.loading")}</p>}
    {data?.length === 0 && <p className="text-sm">{t("sewingEdit.empty")}</p>}
    {!!data?.length && <div className="overflow-x-auto"><table className="table w-full"><thead><tr>
      {["sewingEdit.date", "field.batch", "sewingEdit.line", "sewingEdit.input", "sewingEdit.output", "sewingEdit.passed", "common.actions"].map((key) => <th key={key}>{t(key)}</th>)}
    </tr></thead><tbody>{data.map((row) => <tr key={row.id}>
      <td className="whitespace-nowrap">{new Date(row.created_at).toLocaleString()}</td><td>{batches.some((batch) => batch.id === row.production_batch_id) ? formatBatchLabel(batches.find((batch) => batch.id === row.production_batch_id)!) : "—"}</td><td>{row.line_name || "—"}</td>
      <td>{row.input_qty}</td><td>{row.sewn_qty}</td><td>{row.passed_qty}</td>
      <td><div className="flex gap-2"><button type="button" className="btn" disabled={busy || !!row.locked_reason} onClick={() => { setEditing({ ...row }); setFailure(""); }}><Pencil size={14}/>{t("sewingEdit.edit")}</button>
        <button type="button" className="btn btn-danger" disabled={busy || !!row.locked_reason} onClick={() => void save(row, true)}><Trash2 size={14}/>{t("sewingEdit.delete")}</button></div>
        {row.locked_reason && <p className="mt-1 max-w-xs text-xs">{t(row.locked_reason)}</p>}</td>
    </tr>)}</tbody></table></div>}
    {editing && <form className="border-t pt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); void save(editing); }}>
      <h3 className="font-semibold">{t("sewingEdit.edit")}</h3>
      <fieldset disabled={busy} className="grid gap-3 sm:grid-cols-3">
        {(["input_qty", "sewn_qty", "passed_qty"] as const).map((key, index) => <label className="label" key={key}>{t(["sewingEdit.input", "sewingEdit.output", "sewingEdit.passed"][index])}
          <input className="input" type="number" min={0} step={1} required value={editing[key]} onChange={(event) => setEditing({ ...editing, [key]: Number(event.target.value) })}/></label>)}
        {(editing.size_quantities || []).map((size, index) => <label className="label" key={size.size}>{size.size}<input className="input" type="number" min={0} required value={size.quantity}
          onChange={(event) => setEditing({ ...editing, size_quantities: editing.size_quantities.map((row, i) => i === index ? { ...row, quantity: Number(event.target.value) } : row) })}/></label>)}
      </fieldset>
      <div className="flex gap-2"><button className="btn btn-primary" disabled={busy}>{t("sewingEdit.save")}</button><button type="button" className="btn" disabled={busy} onClick={() => setEditing(null)}>{t("sewingEdit.cancel")}</button></div>
    </form>}
  </section>;
}
