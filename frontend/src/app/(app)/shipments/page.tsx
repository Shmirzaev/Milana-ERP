"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { useDialogs } from "@/components/DialogProvider";

export default function ShipmentsPage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const searchParams = useSearchParams();
  const { data, mutate } = useSWR<any[]>(
    "/api/shipments",
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const { data: orders, mutate: mutateOrders } = useSWR<any[]>(
    "/api/shipments/eligible-orders",
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );

  const [salesOrderId, setSoId] = useState(0);
  const [activeShip, setActive] = useState(0);
  const [scanCode, setScanCode] = useState("");
  const [err, setErr] = useState("");
  const [scanResult, setScanResult] = useState<any | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const so = Number(searchParams.get("so_id") || 0);
    const sh = Number(searchParams.get("shipment_id") || 0);
    if (so > 0) setSoId(so);
    if (sh > 0) setActive(sh);
  }, [searchParams]);

  const shipmentCandidateOrders = useMemo(
    () => (orders || []).slice().sort((a, b) => Number(b.id || 0) - Number(a.id || 0)),
    [orders],
  );

  useEffect(() => {
    if (!orders || !salesOrderId) return;
    const stillEligible = shipmentCandidateOrders.some((order) => Number(order.id) === Number(salesOrderId));
    if (!stillEligible) setSoId(0);
  }, [orders, salesOrderId, shipmentCandidateOrders]);

  const activeShipment = useMemo(
    () => (data || []).find((s) => Number(s.id) === Number(activeShip)) || null,
    [data, activeShip],
  );

  useEffect(() => {
    if (!Array.isArray(data) || data.length === 0) return;
    const exists = data.some((s) => Number(s.id) === Number(activeShip));
    if (!exists) {
      setActive(Number(data[0].id || 0));
    }
  }, [data, activeShip]);

  const { data: scanStatus, mutate: mutateScanStatus } = useSWR<any>(
    activeShip > 0 ? `/api/shipments/${activeShip}/scan-status` : null,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const shipBlockedByScan = Number(scanStatus?.remaining_count || 0) > 0;

  function messageFromError(error: unknown): string {
    if (error instanceof Error && error.message) return error.message;
    return "Action failed.";
  }

  async function create() {
    if (!salesOrderId) return;
    setErr("");
    setMsg("");
    try {
      const sh = await api.post("/api/shipments", { sales_order_id: salesOrderId || null });
      setActive(sh.id);
      setSoId(0);
      setMsg(`Shipment ${sh.shipment_no} created with ${sh.packages_count || 0} package(s).`);
      setScanResult(null);
      setScanCode("");
      await mutate();
      await mutateOrders();
      await mutateScanStatus();
    } catch (error) {
      setErr(messageFromError(error));
    }
  }

  async function addAllReady() {
    setErr("");
    setMsg("");
    try {
      await api.post(`/api/shipments/${activeShip}/add-ready-packages`);
      setMsg(t("page.shipments.allReadyAdded"));
      await mutate();
      await mutateScanStatus();
    } catch (error) {
      setErr(messageFromError(error));
    }
  }

  async function scanPkg() {
    if (!activeShip || !scanCode.trim()) return;
    setErr("");
    setMsg("");
    try {
      const result = await api.post(`/api/shipments/${activeShip}/scan-package`, { code: scanCode.trim() });
      setScanResult(result);
      if (String(result?.sign || "") === "error") {
        setErr(String(result?.message || "Scanned package does not match this shipment."));
      } else {
        setMsg(String(result?.message || "Scan processed."));
      }
      setScanCode("");
      await mutate();
      await mutateScanStatus();
    } catch (error) {
      setErr(messageFromError(error));
    }
  }

  async function ship() {
    setErr("");
    setMsg("");
    if (!(await dialogs.ask({ message: t("page.shipments.confirmMarkShipped") }))) return;
    try {
      await api.post(`/api/shipments/${activeShip}/mark-shipped`);
      setMsg(t("page.shipments.markedShipped"));
      await mutate();
      await mutateScanStatus();
    } catch (error) {
      setErr(messageFromError(error));
    }
  }

  async function deliver() {
    setErr("");
    setMsg("");
    if (!(await dialogs.ask({ message: t("page.shipments.confirmMarkDelivered") }))) return;
    try {
      await api.post(`/api/shipments/${activeShip}/deliver`);
      setMsg(t("page.shipments.markedDelivered"));
      await mutate();
      await mutateScanStatus();
    } catch (error) {
      setErr(messageFromError(error));
    }
  }

  function selectShipment(sh: any) {
    setActive(Number(sh.id || 0));
    setScanResult(null);
    setScanCode("");
    setErr("");
    setSoId(0);
    setMsg(`Selected ${sh.shipment_no}`);
  }

  async function markRowShipped(sh: any) {
    if (!(await dialogs.ask({ message: `Mark ${sh.shipment_no} as shipped?` }))) return;
    await api.post(`/api/shipments/${sh.id}/mark-shipped`);
    mutate();
    if (Number(activeShip) === Number(sh.id)) mutateScanStatus();
  }

  async function markRowDelivered(sh: any) {
    if (!(await dialogs.ask({ message: `Mark ${sh.shipment_no} as delivered?` }))) return;
    await api.post(`/api/shipments/${sh.id}/deliver`);
    mutate();
    if (Number(activeShip) === Number(sh.id)) mutateScanStatus();
  }

  return (
    <div>
      <PageHeader title={t("page.shipments.title")} />
      <div className="max-w-5xl space-y-4">
        <div className="card flex flex-wrap items-end gap-3 p-4">
          <div>
            <label className="label">{t("page.shipments.salesOrder")}</label>
            <select className="input" value={salesOrderId} onChange={(e) => setSoId(Number(e.target.value))}>
              <option value={0}>-</option>
              {shipmentCandidateOrders.map((o) => <option key={o.id} value={o.id}>{o.order_no} - {o.customer_name || o.customer_id || "-"} ({statusLabel(o.status, t)})</option>)}
            </select>
          </div>
          <button className="btn btn-primary" onClick={create} disabled={!salesOrderId}>{t("btn.createShipment")}</button>
          {activeShip > 0 && (
            <>
              <button className="btn" onClick={addAllReady}>{t("page.shipments.addAllReady")}</button>
              <div className="min-w-[320px]">
                <label className="label">{t("page.shipments.scanPackageBeforeShipping")}</label>
                <div className="flex gap-2">
                  <input
                    className="input w-[230px]"
                    value={scanCode}
                    onChange={(e) => setScanCode(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        scanPkg();
                      }
                    }}
                    placeholder={t("ph.packageBarcode")}
                  />
                  <button className="btn" onClick={scanPkg} disabled={!scanCode.trim()}>{t("btn.scan")}</button>
                </div>
              </div>
              <button className="btn" onClick={ship} disabled={shipBlockedByScan}>{t("btn.ship")}</button>
              <button
                className="btn btn-primary"
                onClick={deliver}
                disabled={!activeShipment || String(activeShipment.status || "") === "delivered"}
              >
                {t("btn.markDelivered")}
              </button>
            </>
          )}
          {msg && <div className="w-full text-sm text-emerald-700">{msg}</div>}
          {err && <div className="w-full text-sm text-rose-700">{err}</div>}
          {activeShip > 0 && scanStatus && (
            <div className={`w-full text-xs ${scanStatus.remaining_count > 0 ? "text-amber-700" : "text-emerald-700"}`}>
              {t("page.shipments.scanCheck", { scanned: scanStatus.scanned_count, required: scanStatus.required_count })}
              {scanStatus.remaining_count > 0 ? `, ${t("page.shipments.remaining", { count: scanStatus.remaining_count })}` : "."}
            </div>
          )}
          {scanResult && (
            <div
              className={`w-full text-xs ${
                String(scanResult.sign || "") === "error"
                  ? "text-rose-700"
                  : String(scanResult.sign || "") === "warning"
                    ? "text-amber-700"
                    : "text-emerald-700"
              }`}
            >
              {scanResult.message}
              {scanResult.package_no ? ` (${scanResult.package_no})` : ""}
            </div>
          )}
          {activeShipment && (
            <div className="w-full text-xs text-slate-600">
              {t("page.shipments.activeShipment")} <span className="font-medium">{activeShipment.shipment_no}</span> ({statusLabel(String(activeShipment.status || ""), t)})
            </div>
          )}
        </div>

        <div className="card overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.shipmentNo")}</th>
                <th>{t("field.salesOrderShort")}</th>
                <th>{t("field.customer")}</th>
                <th>{t("field.packages")}</th>
                <th>{t("field.totalQty")}</th>
                <th>{t("field.status")}</th>
                <th>{t("field.shipped")}</th>
                <th>{t("field.delivered")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {data?.map((s) => (
                <tr
                  key={s.id}
                  className={`${s.id === activeShip ? "bg-yellow-50" : ""} cursor-pointer`}
                  onClick={() => selectShipment(s)}
                >
                  <td>{s.shipment_no}</td>
                  <td>{s.sales_order_no || s.sales_order_id || "-"}</td>
                  <td>{s.customer_name || s.customer_id || "-"}</td>
                  <td>{Number(s.packages_count || 0)}</td>
                  <td>{Number(s.total_qty || 0)}</td>
                  <td><span className="badge">{statusLabel(s.status, t)}</span></td>
                  <td>{s.shipped_at ? new Date(s.shipped_at).toLocaleString() : "-"}</td>
                  <td>{s.delivered_at ? new Date(s.delivered_at).toLocaleString() : "-"}</td>
                  <td className="flex flex-wrap gap-2">
                    <button className="btn h-7 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); selectShipment(s); }}>
                      {Number(s.id) === Number(activeShip) ? t("page.shipments.selected") : t("page.shipments.select")}
                    </button>
                    {canTraceability && (
                      <Link
                        className="btn h-7 px-2 text-[11px]"
                        href={`/traceability?shipment=${encodeURIComponent(s.shipment_no || s.id)}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {t("page.shipments.traceability")}
                      </Link>
                    )}
                    {String(s.status || "") !== "shipped" && String(s.status || "") !== "delivered" && (
                      <button className="btn h-7 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); markRowShipped(s); }}>
                        {t("page.shipments.markAsShipped")}
                      </button>
                    )}
                    {String(s.status || "") !== "delivered" && (
                      <button className="btn h-7 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); markRowDelivered(s); }}>
                        {t("page.shipments.markAsDelivered")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
