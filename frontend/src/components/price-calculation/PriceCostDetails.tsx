"use client";
import type { PriceCalculationRequest } from "@/lib/priceCalculationRequests";
import { priceWorkflowMessages } from "@/lib/priceWorkflowMessages";
import { useT } from "@/lib/i18n";

export default function PriceCostDetails({ request }: { request: PriceCalculationRequest }) {
  const { lang } = useT(); const m = priceWorkflowMessages(lang);
  const format = (value: number | null) => value === null ? "—" : new Intl.NumberFormat(lang, { maximumFractionDigits: 4 }).format(value);
  return <div className="space-y-3">
    <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr><th className="py-2 text-left">{m.material}</th><th className="text-right">{m.consumption}</th><th className="text-right">{m.rate}</th><th className="text-right">{m.total}</th></tr></thead><tbody>
      {request.materials.map(row => <tr key={row.key} className="border-t border-[var(--erp-border)]"><td className="py-2">{row.name}</td><td className="text-right tabular-nums">{format(row.consumption)} {row.unit}</td><td className="text-right tabular-nums">{format(row.rate)}</td><td className="text-right tabular-nums">{format(row.cost)}</td></tr>)}
      {[[m.sewing, request.sewing_cost], ...(request.printing_required ? [[m.printing, request.printing_cost]] : []), [m.packaging, request.packaging_cost], ...request.accessories.map(row => [row.name || m.accessories, row.price])].map(([name, cost], index) => <tr key={index} className="border-t border-[var(--erp-border)]"><td className="py-2" colSpan={3}>{name}</td><td className="text-right tabular-nums">{format(cost as number | null)}</td></tr>)}
    </tbody></table></div>
    {request.no_accessories_reason ? <p className="text-sm">{m.noAccessories}: {request.no_accessories_reason}</p> : null}
    <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">{[[m.netCost, request.cost_price], [m.netCostUzs, request.cost_price_uzs], [m.profit, request.difference], [m.margin, request.margin_percentage]].map(([label, value]) => <div key={label}><dt className="text-[var(--erp-text-muted)]">{label}</dt><dd className="mt-1 font-semibold tabular-nums">{format(value as number | null)}</dd></div>)}</dl>
    <p className="text-sm font-medium">{m.selling}: {format(request.selling_price)}</p>
    {request.approved_at ? <p className="text-sm text-[var(--erp-text-muted)]">{m.approvedBy}: {request.approved_by_name || "—"} · {m.approvedAt}: {new Date(request.approved_at).toLocaleString(lang, { timeZone: "Asia/Tashkent" })}</p> : null}
  </div>;
}
