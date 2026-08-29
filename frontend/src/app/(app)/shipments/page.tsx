"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";

import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { useDialogs } from "@/components/DialogProvider";

const warehouseExitText = {
  en: {
    createType: "Exit source",
    fromSalesOrder: "From sales order",
    withoutSalesOrder: "Without sales order",
    exitReference: "Recipient / exit reference",
    exitReferencePlaceholder: "Recipient, destination, or approved reason",
    createWarehouseExit: "Create warehouse exit",
    warehouseExitHint: "Only unreserved packages not owned by a sales order can be issued here. Scan every package before confirming the exit.",
    warehouseExitCreated: "Warehouse exit {shipment} created. Scan the package labels to add products.",
    salesShipmentCreated: "Shipment {shipment} created with {count} package(s).",
    confirmWarehouseExit: "Confirm exit",
    type: "Type",
    reference: "Reference",
    warehouseExit: "Warehouse exit",
  },
  ru: {
    createType: "Источник выдачи",
    fromSalesOrder: "По заказу продажи",
    withoutSalesOrder: "Без заказа продажи",
    exitReference: "Получатель / основание выдачи",
    exitReferencePlaceholder: "Получатель, назначение или утверждённая причина",
    createWarehouseExit: "Создать выдачу со склада",
    warehouseExitHint: "Здесь можно выдать только незарезервированные упаковки, не закреплённые за заказом. Перед подтверждением отсканируйте каждую упаковку.",
    warehouseExitCreated: "Выдача со склада {shipment} создана. Отсканируйте этикетки упаковок, чтобы добавить товар.",
    salesShipmentCreated: "Отгрузка {shipment} создана с упаковками: {count}.",
    confirmWarehouseExit: "Подтвердить выдачу",
    type: "Тип",
    reference: "Основание",
    warehouseExit: "Выдача со склада",
  },
  uz: {
    createType: "Chiqim asosi",
    fromSalesOrder: "Savdo buyurtmasi bo'yicha",
    withoutSalesOrder: "Savdo buyurtmasisiz",
    exitReference: "Qabul qiluvchi / chiqim asosi",
    exitReferencePlaceholder: "Qabul qiluvchi, manzil yoki tasdiqlangan sabab",
    createWarehouseExit: "Ombor chiqimini yaratish",
    warehouseExitHint: "Bu yerda faqat savdo buyurtmasiga biriktirilmagan va band qilinmagan paketlar chiqariladi. Tasdiqlashdan oldin har bir paketni skanerlang.",
    warehouseExitCreated: "{shipment} ombor chiqimi yaratildi. Mahsulot qo'shish uchun paket yorliqlarini skanerlang.",
    salesShipmentCreated: "{shipment} jo'natmasi {count} ta paket bilan yaratildi.",
    confirmWarehouseExit: "Chiqimni tasdiqlash",
    type: "Turi",
    reference: "Asos",
    warehouseExit: "Ombor chiqimi",
  },
} as const;

type WarehouseExitTextKey = keyof typeof warehouseExitText.en;

export default function ShipmentsPage() {
  const { lang, t } = useT();
  const exitT = (key: WarehouseExitTextKey, vars?: Record<string, string | number>) => {
    let value: string = warehouseExitText[lang][key];
    for (const [name, replacement] of Object.entries(vars || {})) {
      value = value.replace(new RegExp(`\\{${name}\\}`, "g"), String(replacement));
    }
    return value;
  };
  const dialogs = useDialogs();
  const { me } = useMe();
  const canTraceability = can(me, "traceability.view");
  const searchParams = useSearchParams();
  const { data, mutate } = useSWR<any[]>("/api/shipments", fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<any[]>("/api/shipments/eligible-orders", fetcher);

  const [salesOrderId, setSoId] = useState(0);
  const [shipmentMode, setShipmentMode] = useState<"sales_order" | "warehouse_exit">("sales_order");
  const [warehouseExitReference, setWarehouseExitReference] = useState("");
  const [activeShip, setActive] = useState(0);
  const [scanCode, setScanCode] = useState("");
  const [err, setErr] = useState("");
  const [scanResult, setScanResult] = useState<any | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    const so = Number(searchParams.get("so_id") || 0);
    const sh = Number(searchParams.get("shipment_id") || 0);
    const mode = searchParams.get("mode");
    if (so > 0) setSoId(so);
    if (sh > 0) setActive(sh);
    if (mode === "warehouse_exit") setShipmentMode("warehouse_exit");
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
  );
  const shipBlockedByScan =
    Number(scanStatus?.required_count || 0) <= 0 || Number(scanStatus?.remaining_count || 0) > 0;

  function messageFromError(error: unknown): string {
    if (error instanceof Error && error.message) return error.message;
    return "Action failed.";
  }

  async function create() {
    const isWarehouseExit = shipmentMode === "warehouse_exit";
    if ((!isWarehouseExit && !salesOrderId) || (isWarehouseExit && !warehouseExitReference.trim())) return;
    setErr("");
    setMsg("");
    try {
      const sh = await api.post("/api/shipments", {
        sales_order_id: isWarehouseExit ? null : salesOrderId,
        notes: isWarehouseExit ? warehouseExitReference.trim() : null,
      });
      setActive(sh.id);
      setSoId(0);
      setWarehouseExitReference("");
      setMsg(
        isWarehouseExit
          ? exitT("warehouseExitCreated", { shipment: sh.shipment_no })
          : exitT("salesShipmentCreated", {
              shipment: sh.shipment_no,
              count: Number(sh.packages_count || 0),
            }),
      );
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
      await api.post(`/api/shipments/${activeShip}/ship`);
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
    setErr("");
    try {
      await api.post(`/api/shipments/${sh.id}/ship`);
      await mutate();
      if (Number(activeShip) === Number(sh.id)) await mutateScanStatus();
    } catch (error) {
      setErr(messageFromError(error));
    }
  }

  async function markRowDelivered(sh: any) {
    if (!(await dialogs.ask({ message: `Mark ${sh.shipment_no} as delivered?` }))) return;
    setErr("");
    try {
      await api.post(`/api/shipments/${sh.id}/deliver`);
      await mutate();
      if (Number(activeShip) === Number(sh.id)) await mutateScanStatus();
    } catch (error) {
      setErr(messageFromError(error));
    }
  }

  return (
    <div>
      <PageHeader title={t("page.shipments.title")} />
      <div className="max-w-5xl space-y-4">
        <div className="card flex flex-wrap items-end gap-3 p-4">
          <div className="w-full sm:w-56">
            <label className="label">{exitT("createType")}</label>
            <select
              className="input"
              value={shipmentMode}
              onChange={(e) => setShipmentMode(e.target.value as "sales_order" | "warehouse_exit")}
            >
              <option value="sales_order">{exitT("fromSalesOrder")}</option>
              <option value="warehouse_exit">{exitT("withoutSalesOrder")}</option>
            </select>
          </div>
          {shipmentMode === "sales_order" ? (
          <div className="w-full min-w-0 sm:flex-1 lg:max-w-md">
            <label className="label">{t("page.shipments.salesOrder")}</label>
            <select className="input" value={salesOrderId} onChange={(e) => setSoId(Number(e.target.value))}>
              <option value={0}>-</option>
              {shipmentCandidateOrders.map((o) => <option key={o.id} value={o.id}>{o.order_no} - {o.customer_name || o.customer_id || "-"} ({statusLabel(o.status, t)})</option>)}
            </select>
          </div>
          ) : (
            <div className="w-full min-w-0 sm:flex-1 lg:max-w-md">
              <label className="label">{exitT("exitReference")}</label>
              <input
                className="input"
                value={warehouseExitReference}
                onChange={(e) => setWarehouseExitReference(e.target.value)}
                placeholder={exitT("exitReferencePlaceholder")}
              />
            </div>
          )}
          <button
            className="btn btn-primary"
            onClick={create}
            disabled={shipmentMode === "sales_order" ? !salesOrderId : !warehouseExitReference.trim()}
          >
            {shipmentMode === "warehouse_exit" ? exitT("createWarehouseExit") : t("btn.createShipment")}
          </button>
          {shipmentMode === "warehouse_exit" && (
            <p className="w-full text-xs text-[#6f6a5b]">{exitT("warehouseExitHint")}</p>
          )}
          {activeShip > 0 && (
            <>
              {activeShipment?.sales_order_id ? (
                <button className="btn" onClick={addAllReady}>{t("page.shipments.addAllReady")}</button>
              ) : null}
              <div className="w-full min-w-0 sm:flex-1 lg:max-w-md">
                <label className="label">{t("page.shipments.scanPackageBeforeShipping")}</label>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <input
                    className="input min-w-0 flex-1"
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
                  <button className="btn w-full sm:w-auto" onClick={scanPkg} disabled={!scanCode.trim()}>{t("btn.scan")}</button>
                </div>
              </div>
              <button
                className="btn"
                onClick={ship}
                disabled={
                  shipBlockedByScan ||
                  !activeShipment ||
                  !["draft", "created"].includes(String(activeShipment.status || ""))
                }
              >
                {activeShipment?.sales_order_id ? t("btn.ship") : exitT("confirmWarehouseExit")}
              </button>
              <button
                className="btn btn-primary"
                onClick={deliver}
                disabled={!activeShipment || String(activeShipment.status || "") !== "shipped"}
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
                <th>{exitT("type")}</th>
                <th>{t("field.salesOrderShort")}</th>
                <th>{t("field.customer")}</th>
                <th>{exitT("reference")}</th>
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
                  <td>{s.sales_order_id ? exitT("fromSalesOrder") : exitT("warehouseExit")}</td>
                  <td>{s.sales_order_no || s.sales_order_id || "-"}</td>
                  <td>{s.customer_name || s.customer_id || "-"}</td>
                  <td className="max-w-[220px] whitespace-normal">{s.notes || "-"}</td>
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
                    {["draft", "created"].includes(String(s.status || "")) && (
                      <button className="btn h-7 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); markRowShipped(s); }}>
                        {t("page.shipments.markAsShipped")}
                      </button>
                    )}
                    {String(s.status || "") === "shipped" && (
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
