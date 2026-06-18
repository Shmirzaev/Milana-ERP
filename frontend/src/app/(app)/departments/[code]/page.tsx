"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { Fragment, useEffect, useMemo, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";

const DEPT_LABELS: Record<string, string> = {
  CUT: "nav.cuttingFloor",
  PRT: "nav.printingFloor",
  SEW: "nav.sewingFloor",
  MIL: "nav.milanaSewing",
  BST: "nav.besttexSewing",
  PKG: "nav.packagingFloor",
  FGS: "nav.finishedGoods",
};

function woActionLink(wo: any) {
  if (wo.operation === "cutting") return `/work-orders/${wo.id}/cutting`;
  if (wo.operation === "printing") return `/work-orders/${wo.id}/printing`;
  if (wo.operation === "sewing") return `/work-orders/${wo.id}/sewing`;
  if (wo.operation === "packaging") return `/work-orders/${wo.id}/packaging`;
  return `/production-orders/${wo.production_order_id}`;
}

function workCardTitle(w: any, t: (key: string, vars?: Record<string, string | number>) => string) {
  return `${orderReference(w, w?.production_order_id ? `#${w.production_order_id}` : "-")} - ${operationLabel(w.operation, t)}`;
}

export default function DepartmentInboxPage() {
  const { t } = useT();
  const params = useParams<{ code: string }>();
  const router = useRouter();
  const code = String(params.code || "").toUpperCase();
  const deptLabel = DEPT_LABELS[code] ? t(DEPT_LABELS[code]) : code;
  const [clientTz, setClientTz] = useState("UTC");
  const [startingWoId, setStartingWoId] = useState<number | null>(null);
  const [startError, setStartError] = useState("");
  const [creatingShipmentFor, setCreatingShipmentFor] = useState<string | null>(null);
  const [shipmentError, setShipmentError] = useState("");

  useEffect(() => {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) setClientTz(tz);
    } catch {
      setClientTz("UTC");
    }
  }, []);

  const { data, isLoading, mutate } = useSWR<any>(code ? `/api/inbox?dept=${code}&tz=${encodeURIComponent(clientTz)}` : null, fetcher, {
    refreshInterval: 10_000,
  });
  const pendingWorkOrders = Array.isArray(data?.pending_work_orders) ? data.pending_work_orders : [];
  const inProgressWorkOrders = Array.isArray(data?.in_progress_work_orders) ? data.in_progress_work_orders : [];
  const activeWorkOrders = Array.isArray(data?.active_work_orders) ? data.active_work_orders : [];
  const incomingWorkOrders = useMemo(
    () => (Array.isArray(data?.incoming_work_orders) ? data.incoming_work_orders : []),
    [data?.incoming_work_orders],
  );
  const incomingWorkOrderPoIds = useMemo(
    () => new Set(incomingWorkOrders.map((row: any) => Number(row.production_order_id || 0)).filter((poId: number) => poId > 0)),
    [incomingWorkOrders],
  );
  const incomingBundleGroups = useMemo(
    () => (Array.isArray(data?.incoming_bundle_groups) ? data.incoming_bundle_groups : [])
      .filter((row: any) => !incomingWorkOrderPoIds.has(Number(row.production_order_id || 0))),
    [data?.incoming_bundle_groups, incomingWorkOrderPoIds],
  );
  const incomingCount = incomingBundleGroups.length + incomingWorkOrders.length;
  const pendingPackages = useMemo(() => (
    Array.isArray(data?.pending_packages) ? data.pending_packages : []
  ), [data?.pending_packages]);
  const readyPackages = useMemo(() => (
    Array.isArray(data?.ready_packages) ? data.ready_packages : []
  ), [data?.ready_packages]);
  const splitQueueByStatus = true;
  const [expandedPackageGroups, setExpandedPackageGroups] = useState<Record<string, boolean>>({});

  const pendingPackagesByOrder = useMemo(() => {
    const groups = new Map<string, { key: string; sales_order_id: number | null; order_no: string | null; sales_order_no: string | null; packages: any[]; total_quantity: number }>();
    for (const p of pendingPackages) {
      const key = p.sales_order_id == null ? "no-so" : `so-${p.sales_order_id}`;
      const existing = groups.get(key) ?? {
        key,
        sales_order_id: p.sales_order_id == null ? null : Number(p.sales_order_id),
        order_no: p.order_no || p.sales_order_no || null,
        sales_order_no: p.sales_order_no || p.order_no || null,
        packages: [],
        total_quantity: 0,
      };
      existing.order_no = existing.order_no || p.order_no || p.sales_order_no || null;
      existing.sales_order_no = existing.sales_order_no || p.sales_order_no || p.order_no || null;
      existing.packages.push(p);
      existing.total_quantity += Number(p.total_quantity || 0);
      groups.set(key, existing);
    }
    return Array.from(groups.values())
      .map((g) => ({
        ...g,
        packages: [...g.packages].sort((a, b) => String(b.package_no || "").localeCompare(String(a.package_no || ""))),
      }))
      .sort((a, b) => {
        const left = a.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        const right = b.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        return left - right;
      });
  }, [pendingPackages]);
  const readyPackagesByOrder = useMemo(() => {
    const groups = new Map<string, { key: string; sales_order_id: number | null; order_no: string | null; sales_order_no: string | null; packages: any[]; total_quantity: number }>();
    for (const p of readyPackages) {
      const key = p.sales_order_id == null ? "no-so" : `so-${p.sales_order_id}`;
      const existing = groups.get(key) ?? {
        key,
        sales_order_id: p.sales_order_id == null ? null : Number(p.sales_order_id),
        order_no: p.order_no || p.sales_order_no || null,
        sales_order_no: p.sales_order_no || p.order_no || null,
        packages: [],
        total_quantity: 0,
      };
      existing.order_no = existing.order_no || p.order_no || p.sales_order_no || null;
      existing.sales_order_no = existing.sales_order_no || p.sales_order_no || p.order_no || null;
      existing.packages.push(p);
      existing.total_quantity += Number(p.total_quantity || 0);
      groups.set(key, existing);
    }
    return Array.from(groups.values())
      .map((g) => ({
        ...g,
        packages: [...g.packages].sort((a, b) => String(b.package_no || "").localeCompare(String(a.package_no || ""))),
      }))
      .sort((a, b) => {
        const left = a.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        const right = b.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        return left - right;
      });
  }, [readyPackages]);
  const readyToShipOrders = useMemo(() => {
    if (Array.isArray(data?.ready_to_ship) && data.ready_to_ship.length > 0) {
      return data.ready_to_ship;
    }
    return readyPackagesByOrder.map((g) => ({
      sales_order_id: g.sales_order_id,
      order_no: g.order_no,
      sales_order_no: g.sales_order_no,
      order_type: "standard",
      shipment_type: "standard",
      customer_name: null,
      customer_address: null,
      destination: null,
      shipment_id: null,
      shipment_no: null,
      shipment_status: "not_created",
      packages: g.packages.length,
      quantity: g.total_quantity,
      pending_qty: 0,
      package_lines: g.packages.map((p: any) => ({
        package_id: p.id,
        package_no: p.package_no,
        reserved_qty: p.total_quantity,
        status: p.status,
      })),
    }));
  }, [data?.ready_to_ship, readyPackagesByOrder]);

  async function movePendingToInProgress(workOrderId: number) {
    setStartingWoId(workOrderId);
    setStartError("");
    try {
      await api.post(`/api/work-orders/${workOrderId}/start`, {});
      await mutate();
    } catch (e: any) {
      setStartError(e?.message || "Failed to move work order to in progress");
    } finally {
      setStartingWoId(null);
    }
  }

  async function createShipmentForOrder(salesOrderId: number | null | undefined) {
    const soId = Number(salesOrderId || 0);
    if (!soId) return;
    const key = `so-${soId}`;
    setShipmentError("");
    setCreatingShipmentFor(key);
    try {
      const created = await api.post("/api/shipments", { sales_order_id: soId });
      await api.post(`/api/shipments/${created.id}/add-ready-packages`);
      await mutate();
      openShipment(soId, created.id);
    } catch (e: any) {
      setShipmentError(e?.message || "Failed to create shipment");
    } finally {
      setCreatingShipmentFor(null);
    }
  }

  function openShipment(salesOrderId: number | null | undefined, shipmentId?: number | null) {
    const soId = Number(salesOrderId || 0);
    const shId = Number(shipmentId || 0);
    const qs = new URLSearchParams();
    if (soId > 0) qs.set("so_id", String(soId));
    if (shId > 0) qs.set("shipment_id", String(shId));
    router.push(`/shipments${qs.toString() ? `?${qs.toString()}` : ""}`);
  }

  function sewingReceivedLine(w: any) {
    if (w?.operation !== "sewing") return null;
    const bundleCount = Number(w.received_bundle_count || 0);
    const qty = Number(w.received_bundle_qty || w.actual_input_qty || 0);
    return (
      <div className="text-xs text-slate-500">
        {t("field.received")}: {bundleCount} {t("nav.bundles").toLowerCase()} / {qty} {t("field.qty").toLowerCase()}
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={t("page.deptInbox.title", { dept: deptLabel })}
        subtitle={t("page.deptInbox.subtitle")}
      />
      {isLoading && <div className="card p-4 text-sm text-slate-500">{t("common.loading")}</div>}
      {!isLoading && (
        <div className={`grid grid-cols-1 gap-4 ${splitQueueByStatus ? "xl:grid-cols-4" : "lg:grid-cols-3"}`}>
          <section className="card p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("page.deptInbox.incoming", { count: incomingCount })}
            </h3>
            <div className="space-y-2">
              {incomingWorkOrders.map((w: any) => (
                <div key={`wo-${w.work_order_id}`} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">{orderReference(w, `#${w.production_order_id}`)}</div>
                      <div className="text-xs text-slate-500">
                        {t("page.deptInbox.incomingProcess", {
                          source: operationLabel(w.source_operation, t),
                          target: operationLabel(w.target_operation, t),
                        })}
                      </div>
                    </div>
                    <span className="badge shrink-0">{statusLabel(w.source_status || w.status, t)}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {Number(w.ready_qty || 0) > 0
                      ? t("page.deptInbox.readyReceived", { ready: w.ready_qty, received: w.received_qty })
                      : t("page.deptInbox.expectedReceived", { expected: w.expected_qty, received: w.received_qty })}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <Link
                      className="text-xs text-brand-600 hover:underline"
                      href={woActionLink({
                        id: w.work_order_id,
                        operation: w.target_operation,
                        production_order_id: w.production_order_id,
                      })}
                    >
                      {t("btn.open")}
                    </Link>
                    <Link className="text-xs text-brand-600 hover:underline" href={`/production-orders/${w.production_order_id}`}>{t("page.deptInbox.viewOrder")}</Link>
                  </div>
                </div>
              ))}
              {incomingBundleGroups.map((g: any) => (
                <div key={`bundle-group-${g.production_order_id}`} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">{orderReference(g, `#${g.production_order_id}`)}</div>
                      <div className="text-xs text-slate-500">
                        {t("page.deptInbox.incomingProcess", {
                          source: operationLabel(g.source_operation || "cutting", t),
                          target: operationLabel(g.target_operation || "sewing", t),
                        })}
                      </div>
                    </div>
                    <span className="badge shrink-0">
                      {Number(g.bundle_count || 0)} {t("nav.bundles").toLowerCase()}
                    </span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {t("page.deptInbox.readyReceived", { ready: g.ready_qty, received: g.received_qty })}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    {g.work_order_id ? (
                      <Link
                        className="text-xs text-brand-600 hover:underline"
                        href={woActionLink({
                          id: g.work_order_id,
                          operation: g.target_operation || "sewing",
                          production_order_id: g.production_order_id,
                        })}
                      >
                        {t("btn.open")}
                      </Link>
                    ) : null}
                    <Link className="text-xs text-brand-600 hover:underline" href={`/production-orders/${g.production_order_id}`}>{t("page.deptInbox.viewOrder")}</Link>
                  </div>
                </div>
              ))}
              {incomingCount === 0 && <div className="text-sm text-slate-400">{t("page.deptInbox.noIncomingWork")}</div>}
            </div>
          </section>

          {splitQueueByStatus ? (
            <>
              <section className="card p-4">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                  {t("page.deptInbox.pending", { count: pendingWorkOrders.length })}
                </h3>
                {startError && <div className="mb-2 text-xs text-red-600">{startError}</div>}
                <div className="space-y-2">
                  {pendingWorkOrders.map((w: any) => (
                    <div key={w.id} className="rounded border border-slate-200 p-2 text-sm">
                      <div className="flex items-center justify-between">
                        <div className="font-medium">{workCardTitle(w, t)}</div>
                        <span className="badge">{statusLabel(w.status, t)}</span>
                      </div>
                      <div className="text-xs text-slate-500">{t("page.deptInbox.passedPlanned", { passed: w.passed_qty, planned: w.planned_output_qty })}</div>
                      {sewingReceivedLine(w)}
                      {w.deadline && (
                        <div className="text-xs text-slate-500">{t("field.deadline")}: {new Date(w.deadline).toLocaleDateString()}</div>
                      )}
                      <div className="mt-1 flex items-center gap-2">
                        <button
                          className="btn h-7 px-2 text-[11px]"
                          onClick={() => movePendingToInProgress(Number(w.id))}
                          disabled={startingWoId === Number(w.id)}
                        >
                          {startingWoId === Number(w.id) ? t("common.loading") : t("btn.moveToInProgress")}
                        </button>
                        <Link className="text-xs text-brand-600 hover:underline" href={woActionLink(w)}>{t("btn.open")}</Link>
                      </div>
                    </div>
                  ))}
                  {pendingWorkOrders.length === 0 && <div className="text-sm text-slate-400">{t("page.deptInbox.noPendingWorkOrders")}</div>}
                </div>
              </section>

              <section className="card p-4">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                  {t("page.deptInbox.inProgress", { count: inProgressWorkOrders.length })}
                </h3>
                <div className="space-y-2">
                  {inProgressWorkOrders.map((w: any) => (
                    <div key={w.id} className="rounded border border-slate-200 p-2 text-sm">
                      <div className="flex items-center justify-between">
                        <div className="font-medium">{workCardTitle(w, t)}</div>
                        <span className="badge">{statusLabel(w.status, t)}</span>
                      </div>
                      <div className="text-xs text-slate-500">{t("page.deptInbox.passedPlanned", { passed: w.passed_qty, planned: w.planned_output_qty })}</div>
                      {sewingReceivedLine(w)}
                      {w.deadline && (
                        <div className="text-xs text-slate-500">{t("field.deadline")}: {new Date(w.deadline).toLocaleDateString()}</div>
                      )}
                      <Link className="text-xs text-brand-600 hover:underline" href={woActionLink(w)}>{t("btn.open")}</Link>
                    </div>
                  ))}
                  {inProgressWorkOrders.length === 0 && <div className="text-sm text-slate-400">{t("page.deptInbox.noInProgressWorkOrders")}</div>}
                </div>
              </section>
            </>
          ) : (
            <section className="card p-4">
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                {t("page.deptInbox.inProgress", { count: activeWorkOrders.length })}
              </h3>
              <div className="space-y-2">
                {activeWorkOrders.map((w: any) => (
                  <div key={w.id} className="rounded border border-slate-200 p-2 text-sm">
                    <div className="flex items-center justify-between">
                      <div className="font-medium">{workCardTitle(w, t)}</div>
                      <span className="badge">{statusLabel(w.status, t)}</span>
                    </div>
                    <div className="text-xs text-slate-500">{t("page.deptInbox.passedPlanned", { passed: w.passed_qty, planned: w.planned_output_qty })}</div>
                    {sewingReceivedLine(w)}
                    {w.deadline && (
                      <div className="text-xs text-slate-500">{t("field.deadline")}: {new Date(w.deadline).toLocaleDateString()}</div>
                    )}
                    <Link className="text-xs text-brand-600 hover:underline" href={woActionLink(w)}>{t("btn.open")}</Link>
                  </div>
                ))}
                {activeWorkOrders.length === 0 && <div className="text-sm text-slate-400">{t("page.deptInbox.noActiveWorkOrders")}</div>}
              </div>
            </section>
          )}

          <section className="card p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("page.deptInbox.doneToday", { count: (data?.done_today || []).length })}
            </h3>
            <div className="space-y-2">
              {(data?.done_today || []).map((w: any) => (
                <div key={w.id} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="font-medium">{workCardTitle(w, t)}</div>
                  <div className="text-xs text-slate-500">{t("page.deptInbox.passedOnly", { passed: w.passed_qty })}</div>
                  <Link className="text-xs text-brand-600 hover:underline" href={`/production-orders/${w.production_order_id}`}>{t("page.deptInbox.viewOrder")}</Link>
                </div>
              ))}
              {(data?.done_today || []).length === 0 && <div className="text-sm text-slate-400">{t("page.deptInbox.nothingCompleted24h")}</div>}
            </div>
          </section>
        </div>
      )}

      {code === "PKG" && data?.awaiting_packaging?.length > 0 && (
        <div className="card mt-4 p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{t("page.deptInbox.awaitingPackaging")}</h3>
          <table className="table">
            <thead>
              <tr><th>{t("field.production")}</th><th>{t("field.readyQty")}</th><th>{t("field.sewn")}</th><th>{t("field.packed")}</th></tr>
            </thead>
            <tbody>
              {data.awaiting_packaging.map((r: any) => (
                <tr key={r.production_order_id}>
                  <td>{orderReference(r, `#${r.production_order_id}`)}</td>
                  <td>{r.ready_qty}</td>
                  <td>{r.sewn_passed}</td>
                  <td>{r.already_packed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {code === "FGS" && (
        <div className="grid grid-cols-1 gap-4 mt-4 lg:grid-cols-2">
          <section className="card p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("page.deptInbox.pendingPackageIntake", { count: pendingPackages.length })}
            </h3>
            <table className="table">
              <thead><tr><th>{t("field.salesOrderShort")}</th><th>{t("field.packages")}</th><th>{t("field.qty")}</th><th className="text-right">{t("field.actions")}</th></tr></thead>
              <tbody>
                {pendingPackagesByOrder.map((g) => (
                  <Fragment key={g.key}>
                    <tr key={g.key}>
                      <td>{orderReference(g, "-")}</td>
                      <td>{g.packages.length}</td>
                      <td>{g.total_quantity}</td>
                      <td className="text-right">
                        <button
                          className="btn h-7 px-2 text-[11px]"
                          onClick={() => setExpandedPackageGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
                        >
                          {expandedPackageGroups[g.key] ? t("common.close") : t("btn.open")}
                        </button>
                      </td>
                    </tr>
                    {expandedPackageGroups[g.key] && (
                      <tr key={`${g.key}-details`}>
                        <td colSpan={4} className="bg-slate-50">
                          <table className="table text-xs">
                            <thead>
                              <tr>
                                <th>{t("field.package")}</th>
                                <th>{t("field.qty")}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {g.packages.map((p: any) => (
                                <tr key={p.id}>
                                  <td>{p.package_no}</td>
                                  <td>{p.total_quantity}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {pendingPackagesByOrder.length === 0 && (
                  <tr><td colSpan={4} className="text-sm text-slate-400">{t("page.deptInbox.noPendingPackages")}</td></tr>
                )}
              </tbody>
            </table>
          </section>
          <section className="card p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("page.deptInbox.readyToShip", { count: readyToShipOrders.length })}
            </h3>
            {shipmentError && <div className="mb-2 text-xs text-red-600">{shipmentError}</div>}
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.salesOrderShort")}</th>
                  <th>{t("field.customer")}</th>
                  <th>{t("field.address")}</th>
                  <th>{t("field.type")}</th>
                  <th>{t("field.shipmentNo")}</th>
                  <th>{t("field.packages")}</th>
                  <th>{t("field.qty")}</th>
                  <th className="text-right">{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {readyToShipOrders.map((g: any) => {
                  const key = `ready-${String(g.sales_order_id ?? "no-so")}`;
                  const soLabel = orderReference(g, "-");
                  const pendingQty = Number(g.pending_qty || 0);
                  const shipmentType = String(g.shipment_type || g.order_type || "standard").replace(/_/g, " ");
                  const shipmentLabel = g.shipment_no ? `${g.shipment_no} (${statusLabel(String(g.shipment_status || ""), t)})` : t("page.deptInbox.notCreated");
                  const soId = Number(g.sales_order_id || 0);
                  const rowKey = `so-${soId}`;
                  return (
                  <Fragment key={key}>
                    <tr>
                      <td>{soLabel}</td>
                      <td>{g.customer_name || "-"}</td>
                      <td className="max-w-[260px] truncate" title={String(g.destination || g.customer_address || "-")}>
                        {g.destination || g.customer_address || "-"}
                      </td>
                      <td>{shipmentType}</td>
                      <td>{shipmentLabel}</td>
                      <td>{Number(g.packages || 0)}</td>
                      <td>
                        <div>{Number(g.quantity || 0)}</div>
                        {pendingQty > 0 && <div className="text-[11px] text-amber-700">{t("page.deptInbox.pendingQty", { qty: pendingQty })}</div>}
                      </td>
                      <td className="text-right">
                        <div className="flex justify-end gap-2">
                          {soId > 0 && (
                            <button
                              className="btn h-7 px-2 text-[11px]"
                              onClick={() => openShipment(soId, Number(g.shipment_id || 0))}
                            >
                              {t("btn.open")}
                            </button>
                          )}
                          <button
                            className="btn h-7 px-2 text-[11px]"
                            onClick={() => {
                              if (g.shipment_id) return;
                              createShipmentForOrder(soId);
                            }}
                            disabled={!soId || !!g.shipment_id || creatingShipmentFor === rowKey}
                          >
                            {creatingShipmentFor === rowKey ? t("common.loading") : t("btn.createShipment")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                )})}
                {readyToShipOrders.length === 0 && (
                  <tr><td colSpan={8} className="text-sm text-slate-400">{t("page.deptInbox.noReadyToShip")}</td></tr>
                )}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
