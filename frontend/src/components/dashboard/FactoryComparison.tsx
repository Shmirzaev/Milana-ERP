"use client";
import { ArrowRight } from "lucide-react";
import { factoryText } from "./messages";
import { Factory, Overview, stageKeys } from "./types";

type Props = {
  data: Overview;
  copy: typeof factoryText.en;
  labels: string[];
  activeLabel: string;
  plannedLabel: string;
  onSelect: (factory: Factory) => void;
};

export default function FactoryComparison({ data, copy, labels, activeLabel, plannedLabel, onSelect }: Props) {
  const border = { borderColor: "var(--erp-border-soft)" };
  return (
    <section className="mb-4 min-w-0 rounded-lg border" style={{ background: "var(--erp-surface)", borderColor: "var(--erp-border)" }}>
      <div className="px-5 py-4">
        <h2 className="text-base font-semibold">{copy.comparison}</h2>
        <p className="mt-1 text-xs" style={{ color: "var(--erp-text-soft)" }}>{copy.scope}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead style={{ background: "var(--erp-surface-muted)", color: "var(--erp-text-soft)" }}>
            <tr>
              <th rowSpan={2} className="px-5 py-2 text-xs font-normal">{copy.factory}</th>
              <th colSpan={2} className="px-5 pb-1 pt-2 text-xs font-normal">{copy.current}</th>
              <th colSpan={4} className="px-5 pb-1 pt-2 text-xs font-normal">{copy.output}</th>
            </tr>
            <tr>{[activeLabel, plannedLabel, ...labels].map(label => <th key={label} className="whitespace-nowrap px-5 pb-2 text-xs font-normal">{label}</th>)}</tr>
          </thead>
          <tbody>
            {data.factories.map(factory => (
              <tr key={factory.code} className="border-t" style={border}>
                <th className="whitespace-nowrap px-5 py-3 font-semibold">
                  <button className="flex items-center gap-2 hover:underline" onClick={() => onSelect(factory.code)} aria-label={`${copy.select}: ${factory.name}`}>
                    {factory.name}<ArrowRight size={14} />
                  </button>
                </th>
                <td className="px-5 py-3 tabular-nums">{factory.active_orders.toLocaleString()}</td>
                <td className="px-5 py-3 tabular-nums">{factory.planned_quantity.toLocaleString()}</td>
                {stageKeys.map(key => <td key={key} className="px-5 py-3 tabular-nums">{factory.totals[key].toLocaleString()}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-1 border-t px-5 py-3 text-xs leading-5" style={{ ...border, color: "var(--erp-text-soft)" }}>
        <p>{copy.shared}</p>
        {data.unassigned_orders > 0 && <p>{copy.unrouted}: {data.unassigned_orders.toLocaleString()}</p>}
        {Object.values(data.unassigned_output).some(Boolean) && <p>{copy.unassigned}</p>}
      </div>
    </section>
  );
}
