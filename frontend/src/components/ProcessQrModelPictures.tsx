"use client";

import { ImageIcon } from "lucide-react";
import { useT } from "@/lib/i18n";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { modelOrderLabel, type ModelVariantModel } from "@/lib/modelVariants";

export default function ProcessQrModelPictures({ model }: { model?: ModelVariantModel }) {
  const { t } = useT();
  const identity = modelOrderLabel(model);
  return <div className="mt-3 flex gap-3" aria-label={t("page.processQr.modelVariant")}>
    {[
      { label: t("field.model"), url: model?.primary_image_url },
      { label: t("page.modelDetail.variant"), url: model?.variant_picture_url },
    ].map(({ label, url }) => <figure key={label} className="w-20 shrink-0">
      <figcaption className="mb-1 text-xs text-[#56503f]">{label}</figcaption>
      {url ? <a href={imagePreviewHref(url, `${label}: ${identity}`)} target="_blank" rel="noopener noreferrer"
        className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-md border border-[#ded9ca] bg-white"
        title={`${label}: ${identity}`}>
        <img src={storageThumbnailUrl(url, 160)} alt={`${label}: ${identity}`} className="h-full w-full object-contain" loading="lazy" />
      </a> : <div className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-md border border-[#ded9ca] bg-[#f4f1e8] text-center text-xs text-[#56503f]"
        aria-label={`${label}: ${t("page.workOrder.noImage")}`}>
        <ImageIcon className="h-4 w-4" aria-hidden="true" />{t("page.workOrder.noImage")}
      </div>}
    </figure>)}
  </div>;
}
