"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { formatOrderReference } from "@/lib/orderRef";
import { statusLabel } from "@/components/StagePipeline";
import { manualShipmentText } from "@/lib/manualShipmentText";
import { shipmentDisplayText, shipmentStatusClass } from "@/lib/shipmentDisplay";
import ShipmentInvoiceActions from "@/components/ShipmentInvoiceActions";
import ShipmentTransportDetails from "@/components/ShipmentTransportDetails";
import type { ShipmentSummary } from "@/components/ShipmentPreparationWorkspace";

type HistoryRow = ShipmentSummary & { shipped_at?: string | null; delivered_at?: string | null };
export default function ShipmentHistoryPage() {
  const { t, lang } = useT();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const manualText = manualShipmentText[lang];
  const { data, mutate, error, isLoading } = useSWR<HistoryRow[]>("/api/shipments", fetcher);
  const [historyQuery, setHistoryQuery] = useState("");
  const [historyStatus, setHistoryStatus] = useState("all");
  const filteredHistory = useMemo(() => {
    const query = historyQuery.trim().toLocaleLowerCase();
    return (data || []).filter((shipment) => {
      if (historyStatus !== "all" && String(shipment.status || "") !== historyStatus) return false;
      if (!query) return true;
      return [shipment.shipment_no, shipment.sales_order_no, shipment.customer_name, shipment.notes]
        .some((value) => String(value || "").toLocaleLowerCase().includes(query));
    });
  }, [data, historyQuery, historyStatus]);

  return <div><PageHeader title={t("page.shipments.history")} actions={<Link className="btn" href="/shipments">{shipmentDisplayText[lang].back}</Link>} />
    {error && <p role="alert">{error.message}</p>}
    {isLoading ? <p>{t("common.loading")}</p> : <>        <section className="card overflow-hidden">
          <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#ded9ca] px-4 py-3 sm:px-5">
            <div><h2 className="app-card-title">{t("page.shipments.history")}</h2><p className="mt-1 text-xs text-[#6f6a5b]">{t("page.shipments.historyHint")}</p></div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:flex-row">
              <input className="input w-full sm:w-72" value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder={t("page.shipments.historySearch")} aria-label={t("page.shipments.historySearch")} />
              <select className="input w-full sm:w-44" value={historyStatus} onChange={(event) => setHistoryStatus(event.target.value)} aria-label={t("field.status")}>
                <option value="all">{t("page.shipments.allStatuses")}</option>
                {["draft", "created", "shipped", "delivered", "cancelled"].map((status) => <option key={status} value={status}>{statusLabel(status, t)}</option>)}
              </select>
            </div>
          </div>
          <div className="divide-y divide-[#ded9ca] md:hidden">
            {filteredHistory.map((shipment) => (
              <article key={shipment.id} className="p-4">
                <div className="flex items-start justify-between gap-3"><div className="mono font-semibold text-[#14110b]">{shipment.shipment_no}</div><span className={`inline-flex border rounded px-2 py-1 text-xs font-medium ${shipmentStatusClass(shipment.status)}`}>{statusLabel(shipment.status, t)}</span></div>
                <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[#56503f]"><span>{shipment.shipment_type === "manual" ? manualText.type : shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</span><span className="text-right mono">{formatOrderReference(shipment.sales_order_no || "-")}</span><span>{shipment.customer_name || "-"}</span><span className="text-right tabular-nums">{Number(shipment.packages_count || 0)} {t("field.packages")} · {Number(shipment.total_qty || 0).toLocaleString()} {t("page.shipments.pieces")}</span></div>
                {["shipped", "delivered"].includes(shipment.status) && <ShipmentInvoiceActions shipmentId={shipment.id} />}
                {(!shipment.sales_order_id || !["draft", "created"].includes(shipment.status)) && <ShipmentTransportDetails shipment={shipment} onChanged={mutate} />}
                {shipment.status !== "cancelled" && <Link className="btn" href={`/shipments?shipment_id=${shipment.id}`}>{shipmentDisplayText[lang].open}</Link>}{canTraceability ? <Link className="btn mt-3 h-8 px-2.5 text-[11px]" href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}>{t("page.shipments.traceability")}</Link> : null}
              </article>
            ))}
            {!filteredHistory.length ? <div className="p-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</div> : null}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="table min-w-[1180px]">
              <thead><tr><th>{t("field.shipmentNo")}</th><th>{t("page.shipments.type")}</th><th>{t("page.shipments.salesOrder")}</th><th>{t("field.customer")}</th><th>{t("page.shipments.reference")}</th><th>{t("field.packages")}</th><th>{t("field.totalQty")}</th><th>{t("field.status")}</th><th>{t("field.shipped")}</th><th>{t("field.delivered")}</th><th>{t("field.actions")}</th></tr></thead>
              <tbody>
                {filteredHistory.map((shipment) => <tr key={shipment.id}><td className="mono whitespace-nowrap font-semibold text-[#14110b]">{shipment.shipment_no}</td><td>{shipment.shipment_type === "manual" ? manualText.type : shipment.sales_order_id ? t("page.shipments.fromSalesOrder") : t("page.shipments.warehouseExit")}</td><td className="mono whitespace-nowrap">{formatOrderReference(shipment.sales_order_no || "-")}</td><td>{shipment.customer_name || "-"}</td><td className="max-w-56 whitespace-normal">{shipment.notes || "-"}{(!shipment.sales_order_id || !["draft", "created"].includes(shipment.status)) && <ShipmentTransportDetails shipment={shipment} onChanged={mutate} />}</td><td className="tabular-nums">{Number(shipment.packages_count || 0)}</td><td className="tabular-nums">{Number(shipment.total_qty || 0).toLocaleString()}</td><td><span className={`inline-flex border rounded px-2 py-1 text-xs font-medium ${shipmentStatusClass(shipment.status)}`}>{statusLabel(shipment.status, t)}</span></td><td className="whitespace-nowrap">{shipment.shipped_at ? new Date(shipment.shipped_at).toLocaleString() : "-"}</td><td className="whitespace-nowrap">{shipment.delivered_at ? new Date(shipment.delivered_at).toLocaleString() : "-"}</td><td>{["shipped", "delivered"].includes(shipment.status) && <ShipmentInvoiceActions shipmentId={shipment.id} />}{shipment.status !== "cancelled" && <Link className="btn" href={`/shipments?shipment_id=${shipment.id}`}>{shipmentDisplayText[lang].open}</Link>}{canTraceability ? <Link className="btn h-8 px-2.5 text-[11px]" href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}>{t("page.shipments.traceability")}</Link> : "-"}</td></tr>)}
                {!filteredHistory.length ? <tr><td colSpan={11} className="py-8 text-center text-sm text-[#6f6a5b]">{t("page.shipments.noHistoryMatches")}</td></tr> : null}
              </tbody>
            </table>
          </div>
        </section></>}
  </div>;
}
