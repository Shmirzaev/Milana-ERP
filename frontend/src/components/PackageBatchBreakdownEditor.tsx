"use client";

import type { PackagePlan } from "@/lib/multiNastilPackaging";
import { flexibleBatchTraceText, packageBatchTraceText, traceCellKey, traceItems, tracePackagePlans, type BatchTraceDraft, type SourceSizeBudgets } from "@/lib/packageBatchTrace";

export default function PackageBatchBreakdownEditor({ plans, draft, onChange, lang, disabled = false, allowUnknown = false, sourceBudgets, sourceSizeBudgets }: {
  plans: PackagePlan[];
  draft: BatchTraceDraft;
  onChange: (draft: BatchTraceDraft) => void;
  lang: "en" | "ru" | "uz";
  disabled?: boolean;
  allowUnknown?: boolean;
  sourceBudgets?: Record<number, number>;
  sourceSizeBudgets?: SourceSizeBudgets;
}) {
  const copy = packageBatchTraceText[lang];
  const mixed = plans.some(plan => (plan.batch_allocations?.length ?? 0) > 1);
  if (!mixed) return null;
  const result = tracePackagePlans(plans, draft, sourceBudgets, sourceSizeBudgets);
  return <section className="space-y-3 border-t border-[#ecebe3] pt-3" aria-label={copy.title}>
    <h4 className="text-sm font-medium">{copy.title}</h4>
    <p className="text-xs text-slate-600">{sourceBudgets ? flexibleBatchTraceText[lang].hint : copy.hint}</p>
    {plans.map((plan, packageIndex) => {
      if ((plan.batch_allocations?.length ?? 0) < 2) return null;
      const items = traceItems(plan.items);
      const traced = result.plans[packageIndex];
      return <div key={packageIndex} className="overflow-x-auto">
        <table className="table text-sm">
          <caption className="pb-2 text-left font-medium">{copy.pack} {packageIndex + 1}</caption>
          <thead><tr><th>{copy.batch}</th>{items.map(item => <th key={traceCellKey(packageIndex, 0, item)}>{item.color} / {item.size}</th>)}<th>{sourceBudgets ? flexibleBatchTraceText[lang].limit : copy.total}</th></tr></thead>
          <tbody>{plan.batch_allocations!.map((allocation) => {
            const actual = traced.batch_allocations!.find(row => row.production_batch_id === allocation.production_batch_id)?.item_breakdown ?? [];
            const total = actual.reduce((sum, item) => sum + item.quantity, 0);
            return <tr key={allocation.production_batch_id}>
              <th scope="row">{allocation.label || copy.missing}</th>
              {items.map(item => {
                const key = traceCellKey(packageIndex, allocation.production_batch_id, item);
                return <td key={key}><input className="input min-w-20" type="number" min={0} step={1}
                  max={Math.min(allocation.quantity, item.quantity, sourceSizeBudgets?.[allocation.production_batch_id] ? sourceSizeBudgets[allocation.production_batch_id][item.size.trim()] ?? 0 : Infinity)} disabled={disabled || (!sourceBudgets && items.length === 1)}
                  aria-label={`${copy.pack} ${packageIndex + 1}, ${allocation.label || copy.missing}, ${item.color} / ${item.size}`}
                  value={!sourceBudgets && items.length === 1 ? allocation.quantity : draft[key] ?? ""}
                  onChange={event => onChange({ ...draft, [key]: event.target.value })} /></td>;
              })}
              <td className="whitespace-nowrap tabular-nums">{total} / {allocation.quantity}</td>
            </tr>;
          })}</tbody>
          <tfoot><tr><th>{copy.total} / {copy.expected}</th>{items.map(item => {
            const total = traced.batch_allocations!.flatMap(row => row.item_breakdown ?? [])
              .filter(row => traceCellKey(0, 0, row) === traceCellKey(0, 0, item)).reduce((sum, row) => sum + row.quantity, 0);
            return <td key={traceCellKey(packageIndex, 0, item)} className="whitespace-nowrap tabular-nums">{total} / {item.quantity}</td>;
          })}<td /></tr></tfoot>
        </table>
      </div>;
    })}
    <p className={`text-sm ${result.valid || allowUnknown ? "text-slate-600" : "text-red-700"}`} role="status">{result.valid ? copy.complete : allowUnknown ? copy.unknown : sourceBudgets ? flexibleBatchTraceText[lang].invalid : copy.invalid}</p>
  </section>;
}
