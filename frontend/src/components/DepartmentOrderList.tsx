"use client";

import Link from "next/link";
import { useMemo } from "react";

import ImageThumbnail from "@/components/ImageThumbnail";
import { operationLabel } from "@/components/StagePipeline";
import type { CtxT } from "@/lib/i18n";
import { formatOrderReference, orderReference } from "@/lib/orderRef";

export type DepartmentOrder = {
  queueKind?: QueueKind;
  id?: number;
  work_order_id?: number | null;
  production_order_id: number;
  planning_order_id?: number | null;
  planning_order_no?: string | null;
  planning_order_name?: string | null;
  order_no?: string | null;
  production_no?: string | null;
  sales_order_no?: string | null;
  model_no?: string | null;
  model_name?: string | null;
  variant_no?: string | null;
  model_image_url?: string | null;
  material_image_url?: string | null;
  material_item_sku?: string | null;
  material_item_name?: string | null;
  size_summary?: string | null;
  size?: string | null;
  textile_code?: string | null;
  textile_name?: string | null;
  operation?: string;
  target_operation?: string;
  source_operation?: string;
  source_status?: string;
  status?: string;
  planned_output_qty?: number | null;
  passed_qty?: number | null;
  ready_qty?: number | null;
  expected_qty?: number | null;
  received_qty?: number | null;
  actual_input_qty?: number | null;
  received_bundle_qty?: number | null;
  received_bundle_count?: number | null;
  bundle_count?: number | null;
  deadline?: string | null;
};

export type QueueKind = "incoming" | "pending" | "in_progress" | "completed";

function actionHref(row: DepartmentOrder) {
  const operation = row.target_operation || row.operation;
  const workOrderId = row.work_order_id || row.id;
  if (workOrderId && ["cutting", "printing", "sewing", "packaging"].includes(operation || "")) {
    return `/work-orders/${workOrderId}/${operation}`;
  }
  return `/production-orders/${row.production_order_id}`;
}

export function mergeDepartmentOrders(queues: Array<{ kind: QueueKind; rows: DepartmentOrder[] }>) {
  const orders = new Map<string, DepartmentOrder>();
  for (const { kind, rows } of queues) {
    for (const row of rows) {
      const workOrderId = row.work_order_id || row.id;
      const key = workOrderId ? `wo-${workOrderId}` : `po-${row.production_order_id}-${row.target_operation || row.operation || "sewing"}-${row.textile_code || "all"}`;
      orders.set(key, { ...orders.get(key), ...row, queueKind: kind });
    }
  }
  return Array.from(orders.values());
}

export function departmentStateFor(row: DepartmentOrder): "not_arrived" | "pending" | "completed" {
  if (row.queueKind === "completed" || row.status === "completed") return "completed";
  // Automatic stage activation alone does not prove that any work has arrived.
  if ([row.ready_qty, row.received_qty, row.received_bundle_qty, row.actual_input_qty, row.passed_qty]
    .some((qty) => Number(qty || 0) > 0)) return "pending";
  return "not_arrived";
}

function rowTone(state: ReturnType<typeof departmentStateFor>) {
  if (state === "completed") return "bg-green-50 hover:!bg-green-100";
  if (state === "pending") return "bg-yellow-50 hover:!bg-amber-100";
  return "bg-white hover:!bg-white";
}

export default function DepartmentOrderList({
  rows, title, emptyLabel, t, startingWorkOrderId, onMoveToInProgress,
}: {
  rows: DepartmentOrder[];
  title: string;
  emptyLabel: string;
  t: CtxT;
  startingWorkOrderId?: number | null;
  onMoveToInProgress?: (workOrderId: number) => void;
}) {
  const groups = useMemo(() => {
    const grouped = new Map<string, DepartmentOrder[]>();
    for (const row of rows) {
      const key = row.planning_order_id ? `bso-${row.planning_order_id}` : `po-${row.production_order_id}`;
      const group = grouped.get(key) || [];
      group.push(row);
      grouped.set(key, group);
    }
    return Array.from(grouped, ([key, orders]) => ({ key, orders }));
  }, [rows]);

  return (
    <section className="card min-w-0 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#e3dfd3] px-4 py-2">
        <h2 className="app-card-title">{title}</h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[#56503f]" aria-label={t("cuttingInbox.colorMeaning")}>
          <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-amber-200 bg-yellow-50" />{t("page.deptInbox.state.pending")}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-green-200 bg-green-50" />{t("page.deptInbox.state.completed")}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-[#ded9ca] bg-white" />{t("page.deptInbox.state.not_arrived")}</span>
        </div>
      </div>
      {groups.length ? groups.map(({ key, orders }) => {
        const first = orders[0];
        const quantity = orders.reduce((sum, row) => sum + Number(row.planned_output_qty ?? (Number(row.expected_qty || row.ready_qty || 0) + Number(row.received_qty || 0))), 0);
        return (
          <div key={key}>
            <div className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1 border-y border-[#ecebe3] bg-[#f1efe8] px-4 py-2 text-sm">
              <span className="mono font-semibold text-[#14110b]">
                {first.planning_order_no
                  ? t("cuttingInbox.bsoNumber", { number: formatOrderReference(first.planning_order_no) })
                  : t("cuttingInbox.orderNumber", { number: orderReference(first) })}
              </span>
              {first.planning_order_name ? <span className="text-[#56503f]">{first.planning_order_name}</span> : null}
              <span className="ml-auto text-xs text-[#8a8472]">{t("cuttingInbox.groupSummary", { orders: orders.length, qty: quantity.toLocaleString() })}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="table min-w-[1180px] [&_tbody_td]:!py-2 [&_thead_th]:!py-2" aria-label={title}>
                <thead>
                  <tr>
                    <th>{t("page.workOrder.modelPicture")}</th>
                    <th>{t("cuttingInbox.variantPicture")}</th>
                    <th>{t("field.production")}</th>
                    <th>{t("field.modelNo")}</th>
                    <th>{t("field.variantNo")}</th>
                    <th>{t("field.size")}</th>
                    <th>{t("cuttingInbox.material")}</th>
                    <th>{t("field.qty")}</th>
                    <th>{t("field.deadline")}</th>
                    <th>{t("field.status")}</th>
                    <th className="text-right">{t("field.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((row) => {
                    const kind = row.queueKind;
                    const state = departmentStateFor(row);
                    const material = [row.material_item_sku, row.material_item_name].filter(Boolean).join(" - ") || "-";
                    return (
                      <tr key={`${row.work_order_id || row.id || row.production_order_id}-${row.textile_code || "all"}`} className={rowTone(state)}>
                        <td><ImageThumbnail imageUrl={row.model_image_url} label={row.model_name || row.model_no || "-"} title={t("page.workOrder.modelPicture")} emptyLabel={t("page.workOrder.noImage")} /></td>
                        <td><ImageThumbnail imageUrl={row.material_image_url} label={material} title={t("cuttingInbox.variantPicture")} emptyLabel={t("page.workOrder.noImage")} /></td>
                        <td className="whitespace-nowrap">
                          <Link className="mono font-semibold text-[#14110b] hover:underline" href={`/production-orders/${row.production_order_id}`}>{orderReference(row)}</Link>
                          <div className="text-xs text-[#56503f]">{kind === "incoming"
                            ? t("page.deptInbox.incomingProcess", { source: operationLabel(row.source_operation || "cutting", t), target: operationLabel(row.target_operation || "sewing", t) })
                            : operationLabel(row.operation || "", t)}</div>
                        </td>
                        <td className="whitespace-nowrap">{row.model_no || row.model_name || "-"}</td>
                        <td className="whitespace-nowrap">{row.variant_no || "-"}</td>
                        <td className="whitespace-nowrap">{row.size_summary || row.size || "-"}</td>
                        <td className="max-w-64" title={material}>
                          <span className="block max-w-64 truncate">{material}</span>
                          {row.textile_name ? <div className="text-xs text-[#56503f]">{t("field.textile")}: {row.textile_name}</div> : null}
                        </td>
                        <td className="whitespace-nowrap">
                          {kind === "incoming"
                            ? Number(row.ready_qty || 0) > 0
                              ? t("page.deptInbox.readyReceived", { ready: Number(row.ready_qty || 0), received: Number(row.received_qty || 0) })
                              : t("page.deptInbox.expectedReceived", { expected: Number(row.expected_qty || 0), received: Number(row.received_qty || 0) })
                            : t("page.deptInbox.passedPlanned", { passed: Number(row.passed_qty || 0), planned: Number(row.planned_output_qty || 0) })}
                          {kind !== "incoming" && Number(row.ready_qty || 0) > 0 ? <div className="text-xs text-[#56503f]">{t("page.deptInbox.readyReceived", { ready: Number(row.ready_qty || 0), received: Number(row.received_qty || 0) })}</div> : null}
                          {row.operation === "sewing" ? <div className="text-xs text-[#56503f]">{t("field.received")}: {Number(row.received_bundle_count || 0)} {t("nav.bundles").toLowerCase()} / {Number(row.received_bundle_qty || row.actual_input_qty || 0)} {t("field.qty").toLowerCase()}</div> : null}
                          {row.bundle_count ? <div className="text-xs text-[#56503f]">{row.bundle_count} {t("nav.bundles").toLowerCase()}</div> : null}
                        </td>
                        <td className="whitespace-nowrap">{row.deadline ? new Date(row.deadline).toLocaleDateString() : "-"}</td>
                        <td className="whitespace-nowrap font-medium">{t(`page.deptInbox.state.${state}`)}</td>
                        <td>
                          <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                            {kind === "pending" && row.id && onMoveToInProgress ? <button type="button" className="btn h-8 px-2.5 text-[11px]" disabled={startingWorkOrderId === row.id} onClick={() => onMoveToInProgress(row.id!)}>{startingWorkOrderId === row.id ? t("common.loading") : t("btn.moveToInProgress")}</button> : null}
                            <Link className="btn btn-primary h-8 px-3 text-[11px]" href={kind === "completed" ? `/production-orders/${row.production_order_id}` : actionHref(row)}>{kind === "completed" ? t("page.deptInbox.viewOrder") : t("btn.open")}</Link>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      }) : <div className="px-4 py-6 text-sm text-[#8a8472]">{emptyLabel}</div>}
    </section>
  );
}
