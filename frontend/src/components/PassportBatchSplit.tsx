"use client";

import { Plus, Trash2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { passportBatchText, passportSplitErrorText, passportSplitProblem, passportUsageQuantity,
  type PassportBatchAllocation, type PassportBatchInfo, type PassportUsageInputs } from "@/lib/passportBatchSplit";

export default function PassportBatchSplit({ material, batches, disabled, locked, pendingIds, onChange, onRemove, onAdd }: {
  material: PassportUsageInputs & { stock_batch_id: number; batch_allocations?: PassportBatchAllocation[] };
  batches: Record<number, PassportBatchInfo>;
  disabled: boolean; locked: boolean; pendingIds: number[];
  onChange: (id: number, quantity: string) => void; onRemove: (id: number) => void; onAdd: () => void;
}) {
  const { lang } = useT();
  const text = passportBatchText(lang);
  const sources = material.batch_allocations || [];
  const unit = material.meter_mode ? "m" : "kg";
  const fmt = (value: number) => value.toLocaleString(lang === "uz" ? "uz-UZ" : lang === "ru" ? "ru-RU" : "en-GB", { maximumFractionDigits: 3 });
  const total = sources.reduce((sum, source) => sum + Math.round((Number(source.quantity) || 0) * 1000), 0) / 1000;
  const problem = passportSplitProblem(material, batches, !locked);
  return <section className="space-y-3 border-b border-[var(--erp-border)] pb-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-medium">{text.title}</h3><span className="text-xs text-[var(--erp-text-soft)]">{text.same}</span>
    </div>
    <p className="text-sm text-[var(--erp-text-soft)]">{text.once}</p>
    {sources.length > 0 && <>
      <div className="space-y-2">
        {sources.map((source, index) => {
          const batch = batches[source.stock_batch_id];
          const label = source.batch_no || batch?.batch_no || "—";
          return <div key={source.stock_batch_id} className="grid grid-cols-[minmax(0,1fr)_minmax(100px,150px)_36px] items-end gap-2 border-t border-[var(--erp-border-soft)] pt-2">
            <div className="min-w-0 space-y-1"><div className="text-xs text-[var(--erp-text-soft)]">{text.batch}</div><div className="break-words font-mono text-sm">{label}</div>
              <div className="text-xs text-[var(--erp-text-soft)]">{text.available}: {batch?.available_quantity != null ? `${fmt(batch.available_quantity)} ${unit}` : "—"}</div></div>
            <label className="block text-xs text-[var(--erp-text-soft)]">{text.amount} ({unit})
              <input className="input mt-1" aria-label={`${text.amount} ${label} (${unit})`} type="number" min="0.001" step="0.001"
                disabled={disabled || locked} value={source.quantity} onChange={event => onChange(source.stock_batch_id, event.target.value)} />
            </label>
            <button type="button" className="btn px-2" aria-label={`${pendingIds.includes(source.stock_batch_id) ? text.remove : text.separate} ${label}`}
              disabled={disabled || locked || index === 0} onClick={() => onRemove(source.stock_batch_id)}><Trash2 className="h-4 w-4" aria-hidden="true" /></button>
          </div>;
        })}
      </div>
      <div className="flex flex-wrap justify-between gap-x-5 gap-y-2 text-sm">
        <span>{text.total}: <strong className="font-mono font-medium">{fmt(total)} {unit}</strong></span>
        <span>{text.expected}: <strong className="font-mono font-medium">{fmt(passportUsageQuantity(material))} {unit}</strong></span>
      </div>
      {problem ? <p role="alert" className="text-sm text-[var(--erp-danger)]">{passportSplitErrorText(problem, lang)}</p>
        : <p role="status" className="text-sm text-[var(--erp-success)]">{text.matched}</p>}
    </>}
    {locked ? <p className="text-sm text-[var(--erp-text-soft)]">{text.locked}</p> : <button type="button" className="btn" disabled={disabled} onClick={onAdd}><Plus className="h-4 w-4" aria-hidden="true" />{text.add}</button>}
  </section>;
}
