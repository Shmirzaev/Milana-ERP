import type { ReactNode } from "react";
import ImageThumbnail from "@/components/ImageThumbnail";
import { priceRequestSurface, type PriceCalculationRequest, type PriceRequestStatus } from "@/lib/priceCalculationRequests";

export function ReadonlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{label}</div>
      <div className="h-8 truncate rounded-md border border-[var(--erp-border)] bg-white/70 px-2 py-1.5 text-sm text-[var(--erp-text)]" title={value || undefined}>
        {value || "—"}
      </div>
    </div>
  );
}

export type PriceRequestProduct = {
  modelNo: string;
  variantNo: string;
  modelName: string;
  sizes: string;
  kroyNo: string;
  modelImageUrl?: string | null;
  variantImageUrl?: string | null;
};

export type PriceRequestProductLabels = {
  model: string;
  variant: string;
  size: string;
  kroy: string;
  modelPicture: string;
  variantPicture: string;
  openPicture: string;
  noPicture: string;
};

export function PriceRequestProductStrip({ product, labels, controls, showKroy = true }: {
  product: PriceRequestProduct;
  labels: PriceRequestProductLabels;
  controls?: { kroy?: ReactNode; variant?: ReactNode };
  showKroy?: boolean;
}) {
  const pictureTitle = (label: string) => `${labels.openPicture}: ${label}`;
  return (
    <div className={`grid grid-cols-2 items-end gap-2 sm:grid-cols-3 ${showKroy ? "lg:grid-cols-[3.75rem_3.75rem_minmax(7rem,0.8fr)_minmax(11rem,1.35fr)_minmax(7rem,0.8fr)_minmax(7rem,0.9fr)]" : "lg:grid-cols-[3.75rem_3.75rem_minmax(11rem,1.35fr)_minmax(7rem,0.8fr)_minmax(7rem,0.9fr)]"}`}>
      <div className="min-w-0">
        <div className="mb-0.5 truncate text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{labels.modelPicture}</div>
        <ImageThumbnail imageUrl={product.modelImageUrl} label={`${product.modelNo} ${labels.modelPicture}`.trim()} title={pictureTitle(labels.modelPicture)} emptyLabel={labels.noPicture} />
      </div>
      <div className="min-w-0">
        <div className="mb-0.5 truncate text-[11px] font-medium leading-3.5 text-[var(--erp-text-muted)]">{labels.variantPicture}</div>
        <ImageThumbnail imageUrl={product.variantImageUrl} label={`${product.variantNo} ${labels.variantPicture}`.trim()} title={pictureTitle(labels.variantPicture)} emptyLabel={labels.noPicture} />
      </div>
      {showKroy ? (controls?.kroy || <ReadonlyField label={labels.kroy} value={product.kroyNo} />) : null}
      <ReadonlyField label={labels.model} value={[product.modelNo, product.modelName].filter(Boolean).join(" · ")} />
      {controls?.variant || <ReadonlyField label={labels.variant} value={product.variantNo} />}
      <ReadonlyField label={labels.size} value={product.sizes} />
    </div>
  );
}

export default function PriceRequestCard({
  request,
  status,
  statusLabel,
  labels,
  children,
}: {
  request: PriceCalculationRequest;
  status: PriceRequestStatus;
  statusLabel: string;
  labels: PriceRequestProductLabels & { request: string };
  children?: ReactNode;
}) {
  return (
    <section className={`rounded-lg border p-2.5 shadow-sm ${priceRequestSurface(status)}`}>
      <div className="mb-2 flex items-center justify-between gap-3 border-b border-black/10 pb-1.5">
        <div className="text-sm font-semibold text-[var(--erp-text-strong)]">{labels.request} #{request.id}</div>
        <div className="text-xs font-medium text-[var(--erp-text-soft)]">{statusLabel}</div>
      </div>
      <PriceRequestProductStrip
        product={{
          modelNo: request.model_no,
          variantNo: request.variant_no,
          modelName: request.model_name,
          sizes: request.model_sizes.join(", "),
          kroyNo: request.kroy_no || "",
          modelImageUrl: request.model_image_url,
          variantImageUrl: request.variant_image_url,
        }}
        labels={labels}
      />
      {children ? <div className="mt-2 border-t border-black/10 pt-2">{children}</div> : null}
    </section>
  );
}
