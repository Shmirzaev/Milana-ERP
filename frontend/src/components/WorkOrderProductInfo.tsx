"use client";

import { useEffect, useMemo, useState } from "react";
import { formatModelComposition } from "@/lib/modelComposition";
import { imagePreviewHref, isPreviewModelImage, storageThumbnailUrl } from "@/lib/modelImages";
import { orderReference } from "@/lib/orderRef";

type Translate = (key: string, vars?: Record<string, string | number>) => string;

type ModelImage = {
  id?: number;
  file_url?: string | null;
  file_name?: string | null;
  content_type?: string | null;
  image_type?: string | null;
  is_primary?: boolean;
};
type ProductImage = ModelImage & {
  source?: "model" | "material";
};

type WorkOrderProductInfoProps = {
  t: Translate;
  so?: any;
  po?: any;
  wo?: any;
  model?: any;
  customerName?: string | null;
  statusText?: string;
  compact?: boolean;
  canEditBreakdown?: boolean;
  onSaveBreakdown?: (items: BreakdownDraftItem[]) => Promise<void>;
};

type BreakdownDraftItem = {
  id?: number | null;
  color: string;
  size: string;
  planned_quantity: number;
};

type BreakdownDraftRow = {
  rowKey: string;
  id?: number | null;
  color: string;
  size: string;
  planned_quantity: string;
};

function isPreviewImage(img: ModelImage): boolean {
  return isPreviewModelImage(img);
}

function imageFromUrl(fileUrl?: string | null, fileName?: string | null, source?: ProductImage["source"]): ProductImage | null {
  const cleanUrl = String(fileUrl || "").trim();
  if (!cleanUrl) return null;
  return {
    file_url: cleanUrl,
    file_name: fileName || cleanUrl.split("/").pop() || cleanUrl,
    content_type: "image/*",
    image_type: source || null,
    source,
  };
}

function selectProductImages(model: any, po?: any, wo?: any): { modelImage: ProductImage | null; materialImage: ProductImage | null } {
  const images: ModelImage[] = Array.isArray(model?.images) ? model.images.filter(isPreviewImage) : [];
  const typedModelImage = images.find((img) => String(img.image_type || "").toLowerCase() === "model") || null;
  const typedMaterialImage = images.find((img) => String(img.image_type || "").toLowerCase() === "material") || null;
  const modelImage =
    imageFromUrl(po?.model_image_url || wo?.model_image_url, tSafeName(po?.model_code || wo?.production_no), "model")
    ||
    typedModelImage
    || images.find((img) => img.is_primary && img !== typedMaterialImage)
    || images.find((img) => img !== typedMaterialImage)
    || null;
  const materialImage =
    imageFromUrl(po?.material_image_url || wo?.material_image_url, tSafeName(po?.material_item_name || wo?.production_no), "material")
    || typedMaterialImage
    || images.find((img) => img !== modelImage)
    || null;

  return { modelImage, materialImage };
}

function tSafeName(value?: string | null): string | null {
  const clean = String(value || "").trim();
  return clean || null;
}

function selectQolipFiles(model: any): ModelImage[] {
  const images: ModelImage[] = Array.isArray(model?.images) ? model.images : [];
  return images.filter((img) => Boolean(img?.file_url) && String(img.image_type || "").toLowerCase() === "pattern");
}

function modelQolipNo(model: any): string {
  const general = model?.details_json?.general || {};
  return String(
    general.qolip_no
      ?? general.qolipNo
      ?? general.mold_no
      ?? general.moldNo
      ?? general.pattern_no
      ?? general.patternNo
      ?? "",
  ).trim();
}

function attachmentName(file: ModelImage, fallback: string): string {
  return file.file_name || String(file.file_url || "").split("/").pop() || fallback;
}

function d(v?: string | null) {
  return v ? new Date(v).toLocaleDateString() : "-";
}

function formatMaterialAmount(amount?: number | string | null, unit?: string | null) {
  if (amount === null || amount === undefined || amount === "") return "-";
  const n = Number(amount);
  if (!Number.isFinite(n)) return "-";
  const formatted = n.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return `${formatted}${unit ? ` ${unit}` : ""}`;
}

function breakdownRowsFromItems(items: any[]): BreakdownDraftRow[] {
  return (items || []).map((it: any, index: number) => ({
    rowKey: it?.id ? `id-${it.id}` : `row-${index}`,
    id: it?.id ?? null,
    color: String(it?.color || ""),
    size: String(it?.size || ""),
    planned_quantity: String(it?.planned_quantity ?? 0),
  }));
}

function ImageSlot({ image, label, fallback }: { image: ProductImage | null; label: string; fallback: string }) {
  const name = image?.file_name || String(image?.file_url || "").split("/").pop() || label;
  const imageUrl = storageThumbnailUrl(image?.file_url, 320);
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="aspect-square overflow-hidden rounded-md border border-[#ecebe3] bg-[#f8f7f3]">
        {imageUrl ? (
          <a href={imagePreviewHref(image?.file_url, name)} target="_blank" rel="noreferrer" className="block h-full w-full">
            <img src={imageUrl} alt={name} className="h-full w-full object-cover" loading="lazy" />
          </a>
        ) : (
          <div className="flex h-full items-center justify-center px-2 text-center text-xs text-slate-400">{fallback}</div>
        )}
      </div>
    </div>
  );
}

export default function WorkOrderProductInfo({
  t,
  so,
  po,
  wo,
  model,
  customerName,
  statusText,
  compact = false,
  canEditBreakdown = false,
  onSaveBreakdown,
}: WorkOrderProductInfoProps) {
  const { modelImage, materialImage } = selectProductImages(model, po, wo);
  const qolipFiles = selectQolipFiles(model);
  const qolipNo = modelQolipNo(model);
  const modelLabel = model ? `${model.code} - ${model.name}` : (po?.model_id ? `#${po.model_id}` : "-");
  const itemPlanTotal = Array.isArray(po?.items)
    ? po.items.reduce((sum: number, it: any) => sum + Math.max(0, Number(it?.planned_quantity || 0)), 0)
    : 0;
  const plannedQty = Number(po?.planned_quantity ?? wo?.planned_output_qty ?? 0);
  const displayedPlannedQty = plannedQty > 0 ? plannedQty : itemPlanTotal;
  const batchQtyTotal = Array.isArray(po?.batches)
    ? po.batches.reduce((sum: number, batch: any) => sum + Math.max(0, Number(batch?.planned_quantity || 0)), 0)
    : 0;
  const displayedActualQty = Math.max(
    0,
    Number(po?.actual_quantity || 0),
    Number(po?.actual_cut_quantity || 0),
    Number(po?.actual_bundle_quantity || 0),
    batchQtyTotal,
  );
  const showActualQty = displayedActualQty > 0 && displayedActualQty !== Number(displayedPlannedQty || 0);
  const isSewingWorkOrder = String(wo?.operation || "").toLowerCase() === "sewing";
  const receivedBundleCount = Number(wo?.received_bundle_count || 0);
  const receivedBundleQty = Number(wo?.received_bundle_qty || wo?.actual_input_qty || 0);
  const showReceivedBundles = isSewingWorkOrder || receivedBundleCount > 0 || receivedBundleQty > 0;
  const canEditCurrentBreakdown = Boolean(canEditBreakdown && onSaveBreakdown && displayedActualQty > 0);
  const [breakdownEditing, setBreakdownEditing] = useState(false);
  const [breakdownRows, setBreakdownRows] = useState<BreakdownDraftRow[]>([]);
  const [breakdownSaving, setBreakdownSaving] = useState(false);
  const [breakdownMsg, setBreakdownMsg] = useState("");
  const breakdownTotal = useMemo(
    () => breakdownRows.reduce((sum, row) => {
      const qty = Number(row.planned_quantity || 0);
      return sum + (Number.isFinite(qty) ? Math.max(0, qty) : 0);
    }, 0),
    [breakdownRows],
  );
  const hasMaterialEstimate = Boolean(
    po?.estimated_material_code
    || po?.estimated_material_amount !== null && po?.estimated_material_amount !== undefined,
  );
  const materialComposition = formatModelComposition(model, po?.estimated_material_composition);
  const displayOrderNo = orderReference({
    order_no: so?.order_no || po?.order_no || wo?.order_no,
    sales_order_no: po?.sales_order_no || wo?.sales_order_no,
    production_no: po?.production_no || wo?.production_no,
    sales_order_id: po?.sales_order_id,
    production_order_id: po?.id || wo?.production_order_id,
  });

  useEffect(() => {
    if (breakdownEditing) return;
    setBreakdownRows(breakdownRowsFromItems(Array.isArray(po?.items) ? po.items : []));
  }, [breakdownEditing, po?.items]);

  function updateBreakdownRow(index: number, patch: Partial<BreakdownDraftRow>) {
    setBreakdownRows((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addBreakdownRow() {
    const first = breakdownRows[0];
    setBreakdownRows((prev) => [
      ...prev,
      {
        rowKey: `new-${Date.now()}-${prev.length}`,
        id: null,
        color: first?.color || "",
        size: "",
        planned_quantity: "1",
      },
    ]);
  }

  function removeBreakdownRow(index: number) {
    setBreakdownRows((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)));
  }

  function openBreakdownEditor() {
    setBreakdownRows(breakdownRowsFromItems(Array.isArray(po?.items) ? po.items : []));
    setBreakdownMsg("");
    setBreakdownEditing(true);
  }

  async function saveBreakdown() {
    if (!onSaveBreakdown) return;
    const normalized = breakdownRows.map((row) => {
      const qty = Number(row.planned_quantity);
      return {
        id: row.id ?? null,
        color: row.color.trim(),
        size: row.size.trim(),
        planned_quantity: qty,
      };
    });

    if (normalized.length === 0) {
      setBreakdownMsg(t("page.workOrder.breakdownRowsRequired"));
      return;
    }
    if (normalized.some((row) => !row.color || !row.size)) {
      setBreakdownMsg(t("page.workOrder.breakdownRequiredFields"));
      return;
    }
    if (normalized.some((row) => !Number.isInteger(row.planned_quantity) || row.planned_quantity <= 0)) {
      setBreakdownMsg(t("page.workOrder.breakdownQuantityRequired"));
      return;
    }
    if (breakdownTotal !== displayedActualQty) {
      setBreakdownMsg(t("page.workOrder.breakdownMismatchTotal", { actual: displayedActualQty, total: breakdownTotal }));
      return;
    }

    setBreakdownSaving(true);
    setBreakdownMsg("");
    try {
      await onSaveBreakdown(normalized);
      setBreakdownEditing(false);
      setBreakdownMsg(t("msg.saved"));
    } catch (e: any) {
      setBreakdownMsg(e?.message || "Failed to save breakdown");
    } finally {
      setBreakdownSaving(false);
    }
  }

  return (
    <div className={`card mb-4 ${compact ? "p-3" : "p-4"}`}>
      <div className={`grid ${compact ? "gap-3 xl:grid-cols-[minmax(0,1fr)_180px]" : "gap-4 xl:grid-cols-[minmax(0,1fr)_260px]"}`}>
        <div className="min-w-0">
          <div className={`${compact ? "mb-2" : "mb-3"} text-xs font-semibold uppercase tracking-[0.08em] text-[#8a8472]`}>
            {t("page.workOrder.productInformation")}
          </div>
          <div className={`grid text-sm ${compact ? "grid-cols-2 gap-x-4 gap-y-2 md:grid-cols-4" : "grid-cols-1 gap-3 md:grid-cols-3"}`}>
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.orderNo")}</div>
              <div className="font-medium">{displayOrderNo}</div>
            </div>
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.customer")}</div>
              <div className="font-medium">{customerName || (so?.customer_id ? `#${so.customer_id}` : "-")}</div>
            </div>
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.model")}</div>
              <div className="font-medium">{modelLabel}</div>
            </div>
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.plannedQty")}</div>
              <div className="font-medium">{displayedPlannedQty}</div>
            </div>
            {showActualQty && (
              <div className="space-y-1">
                <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.actualQty")}</div>
                <div className="font-medium">{displayedActualQty}</div>
              </div>
            )}
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("common.status")}</div>
              <div className="font-medium">{statusText || "-"}</div>
            </div>
            {showReceivedBundles && (
              <div className="space-y-1">
                <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.received")}</div>
                <div className="font-medium">
                  {receivedBundleCount} {t("nav.bundles").toLowerCase()} / {receivedBundleQty} {t("field.qty").toLowerCase()}
                </div>
              </div>
            )}
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.salesDeadline")}</div>
              <div className="font-medium">{d(so?.deadline)}</div>
            </div>
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.poDeadline")}</div>
              <div className="font-medium">{d(po?.deadline)}</div>
            </div>
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.woDeadline")}</div>
              <div className="font-medium">{d(wo?.deadline)}</div>
            </div>
            {hasMaterialEstimate && (
              <>
                <div className="space-y-1">
                  <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.estimatedMaterialCode")}</div>
                  <div className="font-medium">{po?.estimated_material_code || "-"}</div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.estimatedMaterialAmount")}</div>
                  <div className="font-medium">{formatMaterialAmount(po?.estimated_material_amount, po?.estimated_material_unit)}</div>
                </div>
              </>
            )}
            {materialComposition && (
              <div className="space-y-1 md:col-span-2">
                <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.composition")}</div>
                <div className="font-medium">{materialComposition}</div>
              </div>
            )}
            {(qolipNo || qolipFiles.length > 0) && (
              <div className="space-y-1 md:col-span-2">
                <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.qolip")}</div>
                <div className="flex flex-wrap items-center gap-2">
                  {qolipNo && <span className="font-medium">{t("page.workOrder.qolipNo")}: {qolipNo}</span>}
                  {qolipFiles.map((file, index) => (
                    <a
                      key={file.id || `${file.file_url}-${index}`}
                      className="text-brand-600 hover:underline"
                      href={file.file_url || "#"}
                      download
                    >
                      {attachmentName(file, t("page.workOrder.qolipFile"))}
                    </a>
                  ))}
                </div>
              </div>
            )}
          </div>
          {Array.isArray(po?.items) && po.items.length > 0 && (
            <div className={`${compact ? "mt-2 pt-2" : "mt-3 pt-3"} border-t border-[#ecebe3]`}>
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.breakdown")}</div>
                {canEditCurrentBreakdown && !breakdownEditing && (
                  <button type="button" className="btn" onClick={openBreakdownEditor}>
                    {t("btn.edit")}
                  </button>
                )}
              </div>
              {breakdownEditing ? (
                <div className="space-y-3">
                  <div className="overflow-x-auto">
                    <table className="table text-sm">
                      <thead>
                        <tr>
                          <th>{t("field.color")}</th>
                          <th>{t("field.size")}</th>
                          <th>{t("field.qty")}</th>
                          <th>{t("field.actions")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {breakdownRows.map((row, index) => (
                          <tr key={row.rowKey}>
                            <td>
                              <input
                                className="input min-w-32"
                                value={row.color}
                                onChange={(e) => updateBreakdownRow(index, { color: e.target.value })}
                              />
                            </td>
                            <td>
                              <input
                                className="input w-28"
                                value={row.size}
                                onChange={(e) => updateBreakdownRow(index, { size: e.target.value })}
                              />
                            </td>
                            <td>
                              <input
                                className="input w-28"
                                type="number"
                                min={1}
                                step={1}
                                value={row.planned_quantity}
                                onChange={(e) => updateBreakdownRow(index, { planned_quantity: e.target.value })}
                              />
                            </td>
                            <td>
                              <button
                                type="button"
                                className="btn btn-danger"
                                onClick={() => removeBreakdownRow(index)}
                                disabled={breakdownRows.length <= 1 || breakdownSaving}
                              >
                                {t("btn.remove")}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className={`text-sm ${breakdownTotal === displayedActualQty ? "text-slate-600" : "text-red-600"}`}>
                      {t("page.workOrder.breakdownTotal", { total: breakdownTotal, actual: displayedActualQty })}
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                      <button type="button" className="btn" onClick={addBreakdownRow} disabled={breakdownSaving}>
                        {t("common.add")}
                      </button>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => { setBreakdownEditing(false); setBreakdownMsg(""); }}
                        disabled={breakdownSaving}
                      >
                        {t("btn.cancel")}
                      </button>
                      <button type="button" className="btn btn-primary" onClick={saveBreakdown} disabled={breakdownSaving}>
                        {breakdownSaving ? t("common.saving") : t("btn.saveChanges")}
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className={`flex flex-wrap ${compact ? "gap-1" : "gap-2"}`}>
                  {po.items.map((it: any) => (
                    <span key={it.id} className={`rounded-full bg-[#f5f2e8] py-1 text-xs text-[#5d5747] ${compact ? "px-2" : "px-3"}`}>
                      {(it.color || "-")} / {(it.size || "-")} / {it.planned_quantity ?? 0}
                    </span>
                  ))}
                </div>
              )}
              {breakdownMsg && !breakdownEditing && (
                <div className="mt-2 text-sm text-emerald-700">{breakdownMsg}</div>
              )}
              {breakdownMsg && breakdownEditing && (
                <div className="text-sm text-red-600">{breakdownMsg}</div>
              )}
            </div>
          )}
        </div>
        <div className={`grid grid-cols-2 ${compact ? "gap-2" : "gap-3 sm:max-xl:max-w-sm"}`}>
          <ImageSlot image={modelImage} label={t("page.workOrder.modelPicture")} fallback={t("page.workOrder.noImage")} />
          <ImageSlot image={materialImage} label={t("page.workOrder.materialPicture")} fallback={t("page.workOrder.noImage")} />
        </div>
      </div>
    </div>
  );
}
