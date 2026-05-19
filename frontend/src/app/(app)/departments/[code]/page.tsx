"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Fragment, useEffect, useMemo, useState } from "react";

import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

const DEPT_LABELS: Record<string, string> = {
  CUT: "nav.cuttingFloor",
  PRT: "nav.printingFloor",
  SEW: "nav.sewingFloor",
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

export default function DepartmentInboxPage() {
  const { t } = useT();
  const params = useParams<{ code: string }>();
  const code = String(params.code || "").toUpperCase();
  const deptLabel = DEPT_LABELS[code] ? t(DEPT_LABELS[code]) : code;
  const [clientTz, setClientTz] = useState("UTC");

  useEffect(() => {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) setClientTz(tz);
    } catch {
      setClientTz("UTC");
    }
  }, []);

  const { data, isLoading } = useSWR<any>(code ? `/api/inbox?dept=${code}&tz=${encodeURIComponent(clientTz)}` : null, fetcher, {
    refreshInterval: 10_000,
  });
  const pendingWorkOrders = Array.isArray(data?.pending_work_orders) ? data.pending_work_orders : [];
  const inProgressWorkOrders = Array.isArray(data?.in_progress_work_orders) ? data.in_progress_work_orders : [];
  const activeWorkOrders = Array.isArray(data?.active_work_orders) ? data.active_work_orders : [];
  const pendingPackages = Array.isArray(data?.pending_packages) ? data.pending_packages : [];
  const readyPackages = Array.isArray(data?.ready_packages) ? data.ready_packages : [];
  const splitQueueByStatus = code === "PRT";
  const [expandedPackageGroups, setExpandedPackageGroups] = useState<Record<string, boolean>>({});
  const [expandedReadyGroups, setExpandedReadyGroups] = useState<Record<string, boolean>>({});

  const pendingPackagesByOrder = useMemo(() => {
    const groups = new Map<string, { key: string; sales_order_id: number | null; packages: any[]; total_quantity: number }>();
    for (const p of pendingPackages) {
      const key = p.sales_order_id == null ? "no-so" : `so-${p.sales_order_id}`;
      const existing = groups.get(key) ?? {
        key,
        sales_order_id: p.sales_order_id == null ? null : Number(p.sales_order_id),
        packages: [],
        total_quantity: 0,
      };
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
    const groups = new Map<string, { key: string; sales_order_id: number | null; packages: any[]; total_quantity: number }>();
    for (const p of readyPackages) {
      const key = p.sales_order_id == null ? "no-so" : `so-${p.sales_order_id}`;
      const existing = groups.get(key) ?? {
        key,
        sales_order_id: p.sales_order_id == null ? null : Number(p.sales_order_id),
        packages: [],
        total_quantity: 0,
      };
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
              {t("page.deptInbox.incoming", { count: (data?.incoming_bundles || []).length })}
            </h3>
            <div className="space-y-2">
              {(data?.incoming_bundles || []).map((b: any) => (
                <div key={b.id} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="font-medium">{b.bundle_no}</div>
                  <div className="text-xs text-slate-500">{b.color} / {b.size} / {b.quantity}</div>
                  <Link className="text-xs text-brand-600 hover:underline" href={`/bundles/${b.id}`}>{t("page.deptInbox.openBundle")}</Link>
                </div>
              ))}
              {(data?.incoming_bundles || []).length === 0 && <div className="text-sm text-slate-400">{t("page.deptInbox.noIncomingBundles")}</div>}
            </div>
          </section>

          {splitQueueByStatus ? (
            <>
              <section className="card p-4">
                <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
                  {t("page.deptInbox.pending", { count: pendingWorkOrders.length })}
                </h3>
                <div className="space-y-2">
                  {pendingWorkOrders.map((w: any) => (
                    <div key={w.id} className="rounded border border-slate-200 p-2 text-sm">
                      <div className="flex items-center justify-between">
                        <div className="font-medium">WO #{w.id} ({w.operation})</div>
                        <span className="badge">{statusLabel(w.status, t)}</span>
                      </div>
                      <div className="text-xs text-slate-500">{t("page.deptInbox.passedPlanned", { passed: w.passed_qty, planned: w.planned_output_qty })}</div>
                      {w.deadline && (
                        <div className="text-xs text-slate-500">{t("field.deadline")}: {new Date(w.deadline).toLocaleDateString()}</div>
                      )}
                      <Link className="text-xs text-brand-600 hover:underline" href={woActionLink(w)}>{t("btn.open")}</Link>
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
                        <div className="font-medium">WO #{w.id} ({w.operation})</div>
                        <span className="badge">{statusLabel(w.status, t)}</span>
                      </div>
                      <div className="text-xs text-slate-500">{t("page.deptInbox.passedPlanned", { passed: w.passed_qty, planned: w.planned_output_qty })}</div>
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
                      <div className="font-medium">WO #{w.id} ({w.operation})</div>
                      <span className="badge">{statusLabel(w.status, t)}</span>
                    </div>
                    <div className="text-xs text-slate-500">{t("page.deptInbox.passedPlanned", { passed: w.passed_qty, planned: w.planned_output_qty })}</div>
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
                  <div className="font-medium">WO #{w.id} ({w.operation})</div>
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
                  <td>{r.production_no || r.production_order_id}</td>
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
                      <td>{g.sales_order_id || "-"}</td>
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
              {t("page.deptInbox.readyToShip", { count: readyPackagesByOrder.length })}
            </h3>
            <table className="table">
              <thead><tr><th>{t("field.salesOrderShort")}</th><th>{t("field.packages")}</th><th>{t("field.qty")}</th><th className="text-right">{t("field.actions")}</th></tr></thead>
              <tbody>
                {readyPackagesByOrder.map((g) => (
                  <Fragment key={`ready-${g.key}`}>
                    <tr>
                      <td>{g.sales_order_id || "-"}</td>
                      <td>{g.packages.length}</td>
                      <td>{g.total_quantity}</td>
                      <td className="text-right">
                        <button
                          className="btn h-7 px-2 text-[11px]"
                          onClick={() => setExpandedReadyGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
                        >
                          {expandedReadyGroups[g.key] ? t("common.close") : t("btn.open")}
                        </button>
                      </td>
                    </tr>
                    {expandedReadyGroups[g.key] && (
                      <tr>
                        <td colSpan={4} className="bg-slate-50">
                          <table className="table text-xs">
                            <thead>
                              <tr>
                                <th>{t("field.package")}</th>
                                <th>{t("field.qty")}</th>
                                <th>{t("common.status")}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {g.packages.map((p: any) => (
                                <tr key={p.id}>
                                  <td>{p.package_no}</td>
                                  <td>{p.total_quantity}</td>
                                  <td>{statusLabel(String(p.status || ""), t)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {readyPackagesByOrder.length === 0 && (
                  <tr><td colSpan={4} className="text-sm text-slate-400">{t("page.deptInbox.noReadyToShip")}</td></tr>
                )}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
