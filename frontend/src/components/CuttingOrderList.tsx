"use client";

import Link from "next/link";
import { useMemo } from "react";

import ImageThumbnail from "@/components/ImageThumbnail";
import { statusLabel } from "@/components/StagePipeline";
import type { CtxT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";

type CuttingOrder = {
  id: number;
  production_order_id: number;
  planning_order_id?: number | null;
  planning_order_no?: string | null;
  planning_order_name?: string | null;
  order_no?: string | null;
  production_no?: string | null;
  sales_order_no?: string | null;
  model_no?: string | null;
  variant_no?: string | null;
  model_name?: string | null;
  model_image_url?: string | null;
  material_image_url?: string | null;
  material_item_sku?: string | null;
  material_item_name?: string | null;
  size_summary?: string | null;
  planned_output_qty?: number | null;
  passed_qty?: number | null;
  received_bundle_qty?: number | null;
  received_bundle_count?: number | null;
  deadline?: string | null;
  status?: string | null;
};

type CuttingState = "untouched" | "cut_waiting" | "sewing_accepted";

export function cuttingStateFor(row: CuttingOrder): CuttingState {
  if (Number(row.received_bundle_qty || 0) > 0 || Number(row.received_bundle_count || 0) > 0) {
    return "sewing_accepted";
  }
  if (Number(row.passed_qty || 0) > 0 || row.status === "completed") {
    return "cut_waiting";
  }
  return "untouched";
}

function rowTone(state: CuttingState) {
  if (state === "sewing_accepted") return "bg-green-50 hover:bg-green-100";
  if (state === "cut_waiting") return "bg-yellow-50 hover:bg-amber-100";
  return "bg-white hover:bg-[#fdf3eb]";
}

function stateLabel(state: CuttingState, row: CuttingOrder, t: CtxT) {
  if (state === "sewing_accepted") {
    return t("cuttingInbox.sewingAccepted", { qty: Number(row.received_bundle_qty || 0).toLocaleString() });
  }
  if (state === "cut_waiting") return t("cuttingInbox.cutWaiting");
  return statusLabel(String(row.status || "new"), t);
}

function displayValue(...values: Array<string | null | undefined>) {
  return values.map((value) => String(value || "").trim()).filter(Boolean).join(" - ") || "-";
}

export default function CuttingOrderList({
  rows,
  startingWorkOrderId,
  startError,
  onMoveToInProgress,
  t,
}: {
  rows: CuttingOrder[];
  startingWorkOrderId: number | null;
  startError: string;
  onMoveToInProgress: (workOrderId: number) => void;
  t: CtxT;
}) {
  const groups = useMemo(() => {
    const grouped = new Map<string, {
      key: string;
      planningOrderNo: string | null;
      planningOrderName: string | null;
      rows: CuttingOrder[];
    }>();

    for (const row of rows) {
      const planningOrderId = Number(row.planning_order_id || 0);
      const key = planningOrderId > 0 ? `bso-${planningOrderId}` : `order-${row.production_order_id}`;
      const existing = grouped.get(key) || {
        key,
        planningOrderNo: String(row.planning_order_no || "").trim() || null,
        planningOrderName: String(row.planning_order_name || "").trim() || null,
        rows: [],
      };
      existing.rows.push(row);
      grouped.set(key, existing);
    }

    return Array.from(grouped.values());
  }, [rows]);

  return (
    <section className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#e3dfd3] px-4 py-3">
        <h2 className="app-card-title">{t("cuttingInbox.orders", { count: rows.length })}</h2>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[#56503f]" aria-label={t("cuttingInbox.colorMeaning")}>
          <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-[#ded9ca] bg-white" />{t("cuttingInbox.untouched")}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-amber-200 bg-yellow-50" />{t("cuttingInbox.cutWaitingShort")}</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-3 w-3 border border-green-200 bg-green-50" />{t("cuttingInbox.sewingAcceptedShort")}</span>
        </div>
      </div>

      {startError ? <div className="border-b border-[#e3dfd3] px-4 py-2 text-sm text-red-700">{startError}</div> : null}

      {groups.length ? (
        <div className="divide-y divide-[#d8d2c2]">
          {groups.map((group) => {
            const groupQuantity = group.rows.reduce((sum, row) => sum + Number(row.planned_output_qty || 0), 0);
            const first = group.rows[0];
            const groupLabel = group.planningOrderNo
              ? t("cuttingInbox.bsoNumber", { number: group.planningOrderNo })
              : t("cuttingInbox.orderNumber", { number: orderReference(first, `#${first.production_order_id}`) });
            return (
              <section key={group.key}>
                <div className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1 border-b border-[#ecebe3] bg-[#f1efe8] px-4 py-2 text-sm">
                  <span className="mono font-semibold text-[#14110b]">{groupLabel}</span>
                  {group.planningOrderName ? <span className="text-[#56503f]">{group.planningOrderName}</span> : null}
                  <span className="ml-auto text-xs text-[#8a8472]">
                    {t("cuttingInbox.groupSummary", { orders: group.rows.length, qty: groupQuantity.toLocaleString() })}
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="table min-w-[1180px]">
                    <thead>
                      <tr>
                        <th className="w-16">{t("page.workOrder.modelPicture")}</th>
                        <th className="w-16">{t("cuttingInbox.variantPicture")}</th>
                        <th>{t("field.production")}</th>
                        <th>{t("field.modelNo")}</th>
                        <th>{t("field.variantNo")}</th>
                        <th>{t("field.size")}</th>
                        <th>{t("cuttingInbox.material")}</th>
                        <th>{t("cuttingInbox.cutProgress")}</th>
                        <th>{t("field.deadline")}</th>
                        <th>{t("field.status")}</th>
                        <th className="text-right">{t("field.actions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.rows.map((row) => {
                        const state = cuttingStateFor(row);
                        const modelLabel = displayValue(row.model_no, row.model_name);
                        const materialLabel = displayValue(row.material_item_sku, row.material_item_name);
                        const canStart = !["in_progress", "completed"].includes(String(row.status || ""));
                        return (
                          <tr key={row.id} className={rowTone(state)}>
                            <td>
                              <ImageThumbnail
                                imageUrl={row.model_image_url}
                                label={modelLabel}
                                title={t("page.workOrder.modelPicture")}
                                emptyLabel={t("page.workOrder.noImage")}
                              />
                            </td>
                            <td>
                              <ImageThumbnail
                                imageUrl={row.material_image_url}
                                label={displayValue(row.variant_no, materialLabel)}
                                title={t("cuttingInbox.variantPicture")}
                                emptyLabel={t("page.workOrder.noImage")}
                              />
                            </td>
                            <td className="mono whitespace-nowrap font-semibold text-[#14110b]">{orderReference(row, `#${row.production_order_id}`)}</td>
                            <td className="whitespace-nowrap">{row.model_no || row.model_name || "-"}</td>
                            <td className="whitespace-nowrap">{row.variant_no || "-"}</td>
                            <td className="whitespace-nowrap">{row.size_summary || "-"}</td>
                            <td className="max-w-72 whitespace-nowrap" title={materialLabel}><span className="block max-w-72 truncate">{materialLabel}</span></td>
                            <td className="whitespace-nowrap">
                              {Number(row.passed_qty || 0).toLocaleString()} / {Number(row.planned_output_qty || 0).toLocaleString()}
                            </td>
                            <td className="whitespace-nowrap">{row.deadline ? new Date(row.deadline).toLocaleDateString() : "-"}</td>
                            <td className="whitespace-nowrap font-medium">{stateLabel(state, row, t)}</td>
                            <td>
                              <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                                {canStart ? (
                                  <button
                                    type="button"
                                    className="btn h-8 px-2.5 text-[11px]"
                                    onClick={() => onMoveToInProgress(Number(row.id))}
                                    disabled={startingWorkOrderId === Number(row.id)}
                                  >
                                    {startingWorkOrderId === Number(row.id) ? t("common.loading") : t("btn.moveToInProgress")}
                                  </button>
                                ) : null}
                                <Link className="btn btn-primary h-8 px-3 text-[11px]" href={`/work-orders/${row.id}/cutting`}>
                                  {t("btn.open")}
                                </Link>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <div className="px-4 py-8 text-center text-sm text-[#8a8472]">{t("cuttingInbox.noOrders")}</div>
      )}
    </section>
  );
}
