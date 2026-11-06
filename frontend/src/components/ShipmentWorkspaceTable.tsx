"use client";
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { shipmentDisplayText, shipmentStatusClass } from "@/lib/shipmentDisplay";

export type ShipmentWorkspaceRow = {
  key: string; reference: string; order: string; customer: string; status: string;
  packages: number; quantity: number; workspace: ReactNode;
};

export default function ShipmentWorkspaceTable({ rows, requestedKey }: { rows: ShipmentWorkspaceRow[]; requestedKey?: string }) {
  const { t, lang } = useT();
  const text = shipmentDisplayText[lang];
  // Retain mounted forms when collapsed so in-progress scans and edits survive.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const requestedVisible = rows.some(row => row.key === requestedKey);
  useEffect(() => {
    if (!requestedKey || !requestedVisible) return;
    setExpanded(previous => ({ ...previous, [requestedKey]: true }));
    const frame = requestAnimationFrame(() => document.getElementById(`shipment-row-${requestedKey}`)?.scrollIntoView({ block: "start" }));
    return () => cancelAnimationFrame(frame);
  }, [requestedKey, requestedVisible]);
  const allOpen = rows.length > 0 && rows.every(row => expanded[row.key]);
  return <section className="card overflow-hidden">
    <div className="flex justify-end border-b px-4 py-2"><button type="button" className="btn" disabled={!rows.length} onClick={() => setExpanded(previous => ({ ...previous, ...Object.fromEntries(rows.map(row => [row.key, !allOpen])) }))}>{allOpen ? text.collapseAll : text.expandAll}</button></div>
    <div className="overflow-x-auto"><table className="table w-full min-w-[760px]">
      <thead><tr><th>{t("field.shipmentNo")}</th><th>{t("page.shipments.salesOrder")}</th><th>{t("field.customer")}</th><th>{t("field.packages")}</th><th>{t("field.totalQty")}</th><th>{t("field.status")}</th></tr></thead>
      <tbody>{rows.map(row => <Fragment key={row.key}>
        <tr id={`shipment-row-${row.key}`} className="scroll-mt-24">
          <td><button type="button" className="inline-flex items-center gap-2 py-2 text-left font-semibold" aria-expanded={!!expanded[row.key]} aria-controls={`shipment-details-${row.key}`} aria-label={`${expanded[row.key] ? text.collapse : text.expand}: ${row.reference}`} onClick={() => setExpanded(previous => ({ ...previous, [row.key]: !previous[row.key] }))}>
            {expanded[row.key] ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}{row.reference}
          </button></td>
          <td>{row.order || "—"}</td><td>{row.customer || "—"}</td><td className="tabular-nums">{row.packages}</td><td className="tabular-nums">{row.quantity.toLocaleString()}</td>
          <td><span className={`inline-flex border rounded px-2 py-1 text-xs font-medium ${shipmentStatusClass(row.status)}`}>{statusLabel(row.status, t)}</span></td>
        </tr>
        <tr id={`shipment-details-${row.key}`} hidden={!expanded[row.key]}><td colSpan={6} className="!p-0">{Object.hasOwn(expanded, row.key) && row.workspace}</td></tr>
      </Fragment>)}</tbody>
    </table></div>
    {!rows.length && <p className="p-8 text-center text-sm">{t("page.shipments.noOrderMatches")}</p>}
  </section>;
}
