"use client";

import Link from "next/link";
import { Check, PackageCheck, ScanLine } from "lucide-react";
import { useId } from "react";

import ImageThumbnail from "@/components/ImageThumbnail";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

export type ShipmentSummary = {
  id: number;
  sales_order_id?: number | null;
  sales_order_no?: string | null;
  customer_name?: string | null;
  shipment_no: string | null;
  status: string;
  notes?: string | null;
  packages_count?: number | null;
  total_qty?: number | null;
};

type PreparationItemLine = {
  color?: string | null;
  size?: string | null;
  required_qty: number;
  prepared_qty: number;
};

type PreparationItem = {
  model_id: number;
  model_code?: string | null;
  model_no?: string | null;
  variant_no?: string | null;
  model_name?: string | null;
  model_image_url?: string | null;
  variant_image_url?: string | null;
  required_qty: number;
  prepared_qty: number;
  packages_count: number;
  scanned_packages_count: number;
  lines: PreparationItemLine[];
};

type PreparationPackage = {
  id: number;
  package_no: string;
  model_code?: string | null;
  model_no?: string | null;
  variant_no?: string | null;
  model_name?: string | null;
  model_image_url?: string | null;
  variant_image_url?: string | null;
  color?: string | null;
  quantity: number;
  status: string;
  location?: string | null;
  scanned: boolean;
  items: Array<{ color?: string | null; size?: string | null; quantity: number }>;
};

export type ShipmentPreparation = {
  shipment: ShipmentSummary;
  items: PreparationItem[];
  packages: PreparationPackage[];
  required_count: number;
  scanned_count: number;
  remaining_count: number;
  is_complete: boolean;
  is_preview?: boolean;
};

function formatQuantity(value: number | null | undefined) {
  return Number(value || 0).toLocaleString();
}

function variantLabel(color?: string | null, size?: string | null) {
  return [color, size].map((value) => String(value || "").trim()).filter(Boolean).join(" / ") || "-";
}

function modelLabel(item: { model_code?: string | null; model_no?: string | null; model_name?: string | null }) {
  return item.model_no || item.model_code || item.model_name || "-";
}

export default function ShipmentPreparationWorkspace({
  preparation,
  isLoading,
  scanCode,
  onScanCodeChange,
  onScan,
  onAddReadyPackages,
  onShip,
  onDeliver,
  onCreate,
  isCreating = false,
  canTraceability,
}: {
  preparation?: ShipmentPreparation | null;
  isLoading: boolean;
  scanCode: string;
  onScanCodeChange: (value: string) => void;
  onScan: () => void;
  onAddReadyPackages: () => void;
  onShip: () => void;
  onDeliver: () => void;
  onCreate?: () => void;
  isCreating?: boolean;
  canTraceability: boolean;
}) {
  const { t } = useT();
  const scanInputId = useId();

  if (isLoading) {
    return <section className="card px-4 py-10 text-center text-sm text-[#6f6a5b]">{t("page.shipments.loadingPreparation")}</section>;
  }

  if (!preparation) {
    return <section className="card px-4 py-10 text-center text-sm text-[#6f6a5b]">{t("page.shipments.selectPrompt")}</section>;
  }

  const shipment = preparation.shipment;
  const isPreview = Boolean(preparation.is_preview);
  const isOpen = !isPreview && ["draft", "created"].includes(String(shipment.status || ""));
  const canScan = isOpen;
  const shipDisabled = !isOpen || preparation.required_count <= 0 || preparation.remaining_count > 0;
  const items = preparation.items || [];
  const packages = (preparation.packages || []).slice().sort((a, b) => Number(a.scanned) - Number(b.scanned));

  return (
    <section className={`card overflow-hidden ${preparation.is_complete ? "border-emerald-200" : ""}`}>
      <div className={`flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3 sm:px-5 ${preparation.is_complete ? "border-emerald-200 bg-emerald-50" : "border-[#ded9ca] bg-[#f1efe8]"}`}>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="app-card-title mono">{shipment.shipment_no || shipment.sales_order_no}</h2>
            <span className="badge">{isPreview ? t("page.shipments.notCreated") : statusLabel(shipment.status, t)}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-[#56503f]">
            <span>{t("page.shipments.salesOrder")}: <strong className="font-semibold text-[#14110b]">{shipment.sales_order_no || "-"}</strong></span>
            <span>{t("field.customer")}: <strong className="font-semibold text-[#14110b]">{shipment.customer_name || "-"}</strong></span>
            {!shipment.sales_order_id && shipment.notes ? <span>{t("page.shipments.reference")}: {shipment.notes}</span> : null}
          </div>
        </div>
        <div className="text-right text-sm tabular-nums text-[#56503f]">
          <div>{formatQuantity(shipment.total_qty)} {t("page.shipments.pieces")}</div>
          <div>{formatQuantity(shipment.packages_count)} {t("field.packages")}</div>
        </div>
      </div>

      <div className="border-b border-[#ded9ca] bg-[#f8f6ef] px-4 py-4 sm:px-5">
        <div className="grid gap-3 lg:grid-cols-[minmax(320px,1fr)_auto] lg:items-end">
          <div>
            <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
              <label className="label mb-0" htmlFor={scanInputId}>{t("page.shipments.scanPackageBeforeShipping")}</label>
              <span className={`text-xs font-medium ${preparation.is_complete ? "text-emerald-700" : "text-[#6f6a5b]"}`}>
                {isPreview
                  ? t("page.shipments.createToScan")
                  : t("page.shipments.scanProgress", {
                      scanned: preparation.scanned_count,
                      required: preparation.required_count,
                      remaining: preparation.remaining_count,
                    })}
              </span>
            </div>
            <div className="flex gap-2">
              <div className="relative min-w-0 flex-1">
                <ScanLine className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" aria-hidden="true" />
                <input
                  id={scanInputId}
                  className="input pl-9"
                  value={scanCode}
                  onChange={(event) => onScanCodeChange(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      onScan();
                    }
                  }}
                  placeholder={t("ph.packageBarcode")}
                  autoComplete="off"
                  disabled={!canScan}
                />
              </div>
              <button type="button" className="btn btn-primary shrink-0" onClick={onScan} disabled={!canScan || !scanCode.trim()}>
                {t("btn.scan")}
              </button>
            </div>
          </div>

          {!isPreview ? <div className="flex flex-wrap gap-2 lg:justify-end">
            {shipment.sales_order_id && isOpen ? (
              <button type="button" className="btn" onClick={onAddReadyPackages}>{t("page.shipments.addReadyPackages")}</button>
            ) : null}
            <button type="button" className="btn" onClick={onShip} disabled={shipDisabled}>
              {shipment.sales_order_id ? t("btn.ship") : t("page.shipments.confirmWarehouseExit")}
            </button>
            <button type="button" className="btn btn-primary" onClick={onDeliver} disabled={shipment.status !== "shipped"}>
              {t("btn.markDelivered")}
            </button>
            {canTraceability ? (
              <Link className="btn" href={`/traceability?shipment=${encodeURIComponent(shipment.shipment_no || shipment.id)}`}>
                {t("page.shipments.traceability")}
              </Link>
            ) : null}
          </div> : onCreate ? (
            <div className="flex lg:justify-end">
              <button type="button" className="btn btn-primary" onClick={onCreate} disabled={isCreating}>
                {isCreating ? t("common.loading") : t("btn.createShipment")}
              </button>
            </div>
          ) : null}
        </div>
      </div>

      <div className="border-b border-[#ded9ca]">
        <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-5">
          <h3 className="font-semibold text-[#14110b]">{t("page.shipments.itemsToPrepare")}</h3>
          <span className="text-xs text-[#6f6a5b]">{t("page.shipments.modelVariantPictures")}</span>
        </div>
        {items.length ? (
          <>
            <div className="divide-y divide-[#ded9ca] border-t border-[#ded9ca] md:hidden">
              {items.map((item) => {
                const prepared = item.required_qty > 0 && item.prepared_qty >= item.required_qty;
                const scanned = item.packages_count > 0 && item.scanned_packages_count >= item.packages_count;
                const partial = item.prepared_qty > 0 && !prepared;
                return (
                  <article key={item.model_id} className={`p-4 ${scanned ? "bg-emerald-50/60" : partial ? "bg-amber-50/60" : ""}`}>
                    <div className="flex items-start gap-3">
                      <div className="flex shrink-0 gap-2">
                        <ImageThumbnail
                          imageUrl={item.model_image_url}
                          label={modelLabel(item)}
                          title={t("page.workOrder.modelPicture")}
                          emptyLabel={t("page.workOrder.noImage")}
                        />
                        <ImageThumbnail
                          imageUrl={item.variant_image_url}
                          label={item.variant_no || modelLabel(item)}
                          title={t("page.shipments.variantPicture")}
                          emptyLabel={t("page.workOrder.noImage")}
                        />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold text-[#14110b]">{modelLabel(item)}</div>
                        <div className="text-xs text-[#56503f]">{t("field.variantNo")}: {item.variant_no || "-"}</div>
                        {item.model_name && item.model_name !== modelLabel(item) ? <div className="mt-0.5 text-xs text-[#6f6a5b]">{item.model_name}</div> : null}
                      </div>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 border-y border-[#ded9ca] py-2 text-xs">
                      {item.lines.filter((line) => line.required_qty > 0).map((line, index) => (
                        <div key={`${line.color}-${line.size}-${index}`} className="contents">
                          <span>{variantLabel(line.color, line.size)}</span>
                          <span className="text-right font-medium tabular-nums">{formatQuantity(line.required_qty)}</span>
                        </div>
                      ))}
                    </div>
                    <div className="mt-3 flex items-end justify-between gap-3">
                      <div className="text-xs text-[#6f6a5b]">
                        <div>{t("page.shipments.prepared")}: <strong className="font-semibold tabular-nums text-[#14110b]">{formatQuantity(item.prepared_qty)} / {formatQuantity(item.required_qty)}</strong></div>
                        <div>{t("field.packages")}: {item.scanned_packages_count} / {item.packages_count} {t("page.shipments.verifiedShort")}</div>
                      </div>
                      <span className={`text-right text-xs font-medium ${scanned ? "text-emerald-700" : partial ? "text-amber-700" : "text-[#56503f]"}`}>
                        {scanned
                          ? t("page.shipments.scanned")
                          : prepared
                            ? t("page.shipments.notScanned")
                            : partial
                              ? t("page.shipments.partiallyPrepared")
                              : t("page.shipments.notScanned")}
                      </span>
                    </div>
                  </article>
                );
              })}
            </div>
            <div className="hidden overflow-x-auto md:block">
            <table className="table min-w-[960px]">
              <thead>
                <tr>
                  <th className="w-16">{t("page.workOrder.modelPicture")}</th>
                  <th className="w-16">{t("page.shipments.variantPicture")}</th>
                  <th>{t("page.shipments.modelAndVariant")}</th>
                  <th>{t("page.shipments.orderBreakdown")}</th>
                  <th>{t("page.shipments.prepared")}</th>
                  <th>{t("field.packages")}</th>
                  <th>{t("field.status")}</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const prepared = item.required_qty > 0 && item.prepared_qty >= item.required_qty;
                  const scanned = item.packages_count > 0 && item.scanned_packages_count >= item.packages_count;
                  const partial = item.prepared_qty > 0 && !prepared;
                  return (
                    <tr key={item.model_id} className={scanned ? "bg-emerald-50/60" : partial ? "bg-amber-50/60" : ""}>
                      <td>
                        <ImageThumbnail
                          imageUrl={item.model_image_url}
                          label={modelLabel(item)}
                          title={t("page.workOrder.modelPicture")}
                          emptyLabel={t("page.workOrder.noImage")}
                        />
                      </td>
                      <td>
                        <ImageThumbnail
                          imageUrl={item.variant_image_url}
                          label={item.variant_no || modelLabel(item)}
                          title={t("page.shipments.variantPicture")}
                          emptyLabel={t("page.workOrder.noImage")}
                        />
                      </td>
                      <td>
                        <div className="font-semibold text-[#14110b]">{modelLabel(item)}</div>
                        <div className="text-xs text-[#56503f]">{t("field.variantNo")}: {item.variant_no || "-"}</div>
                        {item.model_name && item.model_name !== modelLabel(item) ? <div className="mt-0.5 max-w-64 text-xs text-[#6f6a5b]">{item.model_name}</div> : null}
                      </td>
                      <td>
                        <div className="space-y-1 text-xs">
                          {item.lines.filter((line) => line.required_qty > 0).map((line, index) => (
                            <div key={`${line.color}-${line.size}-${index}`} className="flex min-w-56 items-center justify-between gap-4">
                              <span>{variantLabel(line.color, line.size)}</span>
                              <span className="font-medium tabular-nums">{formatQuantity(line.required_qty)}</span>
                            </div>
                          ))}
                        </div>
                      </td>
                      <td className="whitespace-nowrap tabular-nums">
                        <span className="font-semibold text-[#14110b]">{formatQuantity(item.prepared_qty)}</span>
                        <span className="text-[#8a8472]"> / {formatQuantity(item.required_qty)}</span>
                      </td>
                      <td className="whitespace-nowrap tabular-nums">
                        {item.scanned_packages_count} / {item.packages_count} {t("page.shipments.verifiedShort")}
                      </td>
                      <td className={`whitespace-nowrap font-medium ${scanned ? "text-emerald-700" : partial ? "text-amber-700" : "text-[#56503f]"}`}>
                        {scanned
                          ? t("page.shipments.scanned")
                          : prepared
                            ? t("page.shipments.notScanned")
                            : partial
                              ? t("page.shipments.partiallyPrepared")
                              : t("page.shipments.notScanned")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </>
        ) : (
          <div className="px-4 pb-6 text-sm text-[#6f6a5b] sm:px-5">{t("page.shipments.noPreparationItems")}</div>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-5">
          <h3 className="font-semibold text-[#14110b]">{t("page.shipments.packageChecklist")}</h3>
          <span className="text-xs tabular-nums text-[#6f6a5b]">
            {preparation.scanned_count} / {preparation.required_count} {t("page.shipments.verifiedShort")}
          </span>
        </div>
        {packages.length ? (
          <>
            <div className="divide-y divide-[#ded9ca] border-t border-[#ded9ca] md:hidden">
              {packages.map((pkg) => (
                <article key={pkg.id} className={`p-4 ${pkg.scanned ? "bg-emerald-50/60" : ""}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="mono font-semibold text-[#14110b]">{pkg.package_no}</div>
                      <div className="mt-1 text-xs text-[#56503f]">{modelLabel(pkg)} · {t("field.variantNo")}: {pkg.variant_no || "-"}</div>
                    </div>
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${pkg.scanned ? "text-emerald-700" : "text-[#56503f]"}`}>
                      {pkg.scanned ? <Check className="h-4 w-4" aria-hidden="true" /> : <PackageCheck className="h-4 w-4" aria-hidden="true" />}
                      {pkg.scanned ? t("page.shipments.scanned") : t("page.shipments.notScanned")}
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 border-t border-[#ded9ca] pt-3 text-xs">
                    <div>
                      <div className="label mb-1">{t("page.shipments.contents")}</div>
                      <div className="space-y-1">
                        {pkg.items.length ? pkg.items.map((line, index) => (
                          <div key={`${line.color}-${line.size}-${index}`}>{variantLabel(line.color, line.size)} · {formatQuantity(line.quantity)}</div>
                        )) : <span>{pkg.color || "-"}</span>}
                      </div>
                    </div>
                    <div>
                      <div className="label mb-1">{t("page.shipments.storageLocation")}</div>
                      <div>{pkg.location || "-"}</div>
                      <div className="mt-2 text-[#6f6a5b]">{t("field.totalQty")}: <strong className="font-semibold tabular-nums text-[#14110b]">{formatQuantity(pkg.quantity)}</strong></div>
                    </div>
                  </div>
                </article>
              ))}
            </div>
            <div className="hidden overflow-x-auto md:block">
            <table className="table min-w-[900px]">
              <thead>
                <tr>
                  <th>{t("page.shipments.package")}</th>
                  <th>{t("page.shipments.modelAndVariant")}</th>
                  <th>{t("page.shipments.contents")}</th>
                  <th>{t("page.shipments.storageLocation")}</th>
                  <th>{t("field.totalQty")}</th>
                  <th>{t("page.shipments.scanState")}</th>
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg) => (
                  <tr key={pkg.id} className={pkg.scanned ? "bg-emerald-50/60" : ""}>
                    <td className="mono whitespace-nowrap font-semibold text-[#14110b]">{pkg.package_no}</td>
                    <td>
                      <div className="font-medium text-[#14110b]">{modelLabel(pkg)}</div>
                      <div className="text-xs text-[#56503f]">{t("field.variantNo")}: {pkg.variant_no || "-"}</div>
                    </td>
                    <td>
                      <div className="space-y-1 text-xs">
                        {pkg.items.length ? pkg.items.map((line, index) => (
                          <div key={`${line.color}-${line.size}-${index}`}>
                            {variantLabel(line.color, line.size)} · {formatQuantity(line.quantity)}
                          </div>
                        )) : <span>{pkg.color || "-"}</span>}
                      </div>
                    </td>
                    <td className="whitespace-nowrap">{pkg.location || "-"}</td>
                    <td className="tabular-nums">{formatQuantity(pkg.quantity)}</td>
                    <td>
                      <span className={`inline-flex items-center gap-1.5 whitespace-nowrap font-medium ${pkg.scanned ? "text-emerald-700" : "text-[#56503f]"}`}>
                        {pkg.scanned ? <Check className="h-4 w-4" aria-hidden="true" /> : <PackageCheck className="h-4 w-4" aria-hidden="true" />}
                        {pkg.scanned ? t("page.shipments.scanned") : t("page.shipments.notScanned")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </>
        ) : (
          <div className="px-4 pb-6 text-sm text-[#6f6a5b] sm:px-5">{t("page.shipments.noPackagesAttached")}</div>
        )}
      </div>
    </section>
  );
}
