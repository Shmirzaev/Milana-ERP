type Translate = (key: string, vars?: Record<string, string | number>) => string;

type ModelImage = {
  id?: number;
  file_url?: string | null;
  file_name?: string | null;
  content_type?: string | null;
  image_type?: string | null;
  is_primary?: boolean;
};

type WorkOrderProductInfoProps = {
  t: Translate;
  so?: any;
  po?: any;
  wo?: any;
  model?: any;
  customerName?: string | null;
  statusText?: string;
};

function isPreviewImage(img: ModelImage): boolean {
  const contentType = String(img.content_type || "").toLowerCase();
  const name = String(img.file_name || img.file_url || "").toLowerCase();
  return contentType.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(name);
}

function selectProductImages(model: any): { modelImage: ModelImage | null; materialImage: ModelImage | null } {
  const images: ModelImage[] = Array.isArray(model?.images) ? model.images.filter(isPreviewImage) : [];
  const typedModelImage = images.find((img) => String(img.image_type || "").toLowerCase() === "model") || null;
  const typedMaterialImage = images.find((img) => String(img.image_type || "").toLowerCase() === "material") || null;
  const modelImage =
    typedModelImage
    || images.find((img) => img.is_primary && img !== typedMaterialImage)
    || images.find((img) => img !== typedMaterialImage)
    || null;
  const materialImage =
    typedMaterialImage
    || images.find((img) => img !== modelImage)
    || null;

  return { modelImage, materialImage };
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

function ImageSlot({ image, label, fallback }: { image: ModelImage | null; label: string; fallback: string }) {
  const name = image?.file_name || String(image?.file_url || "").split("/").pop() || label;
  return (
    <div className="min-w-0">
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="aspect-square overflow-hidden rounded-md border border-[#ecebe3] bg-[#f8f7f3]">
        {image?.file_url ? (
          <img src={image.file_url} alt={name} className="h-full w-full object-cover" loading="lazy" />
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
}: WorkOrderProductInfoProps) {
  const { modelImage, materialImage } = selectProductImages(model);
  const modelLabel = model ? `${model.code} - ${model.name}` : (po?.model_id ? `#${po.model_id}` : "-");
  const itemPlanTotal = Array.isArray(po?.items)
    ? po.items.reduce((sum: number, it: any) => sum + Math.max(0, Number(it?.planned_quantity || 0)), 0)
    : 0;
  const displayedPlannedQty = itemPlanTotal > 0 ? itemPlanTotal : (po?.planned_quantity ?? wo?.planned_output_qty ?? 0);
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
  const showActualQty = displayedActualQty > Number(displayedPlannedQty || 0);
  const hasMaterialEstimate = Boolean(
    po?.estimated_material_code
    || po?.estimated_material_amount !== null && po?.estimated_material_amount !== undefined,
  );

  return (
    <div className="card mb-4 p-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_260px]">
        <div className="min-w-0">
          <div className="mb-3 text-xs font-semibold uppercase tracking-[0.08em] text-[#8a8472]">
            {t("page.workOrder.productInformation")}
          </div>
          <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.shipments.salesOrder")}</div>
              <div className="font-medium">{so?.order_no || (po?.sales_order_id ? `#${po.sales_order_id}` : "-")}</div>
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
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.productionOrder")}</div>
              <div className="font-medium">{po?.production_no || (po?.id ? `#${po.id}` : "-")}</div>
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
          </div>
          {Array.isArray(po?.items) && po.items.length > 0 && (
            <div className="mt-3 border-t border-[#ecebe3] pt-3">
              <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.breakdown")}</div>
              <div className="flex flex-wrap gap-2">
                {po.items.map((it: any) => (
                  <span key={it.id} className="rounded-full bg-[#f5f2e8] px-3 py-1 text-xs text-[#5d5747]">
                    {(it.color || "-")} / {(it.size || "-")} / {it.planned_quantity ?? 0}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3 sm:max-xl:max-w-sm">
          <ImageSlot image={modelImage} label={t("page.workOrder.modelPicture")} fallback={t("page.workOrder.noImage")} />
          <ImageSlot image={materialImage} label={t("page.workOrder.materialPicture")} fallback={t("page.workOrder.noImage")} />
        </div>
      </div>
    </div>
  );
}
