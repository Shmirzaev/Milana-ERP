"use client";

import useSWR from "swr";
import { ImageIcon } from "lucide-react";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { imagePreviewHref, isPreviewModelImage, storageThumbnailUrl, type ModelImageLike } from "@/lib/modelImages";
import { modelOrderLabel, type ModelVariantModel } from "@/lib/modelVariants";

type ModelDetail = ModelVariantModel & {
  images: (ModelImageLike & { id: number; image_type?: string | null; is_primary?: boolean })[];
  bom: {
    id: number;
    material_role?: string | null;
    photo_url?: string | null;
    item?: { category?: string | null; image_url?: string | null } | null;
  }[];
};

export default function SalesLineThumbnails({ modelId }: { modelId: number }) {
  const { t } = useT();
  const { data: model, isLoading, error } = useSWR<ModelDetail>(
    modelId > 0 ? `/api/models/${modelId}` : null,
    fetcher,
  );

  if (!modelId) return null;

  const images = (model?.images || []).filter(isPreviewModelImage).slice().sort((a, b) => b.id - a.id);
  const modelImages = images.filter((image) => image.image_type === "model" || !image.image_type);
  const modelImage = modelImages.find((image) => image.is_primary) || modelImages[0];
  const materialImage = images.find((image) => image.image_type === "material");
  const fabrics = (model?.bom || [])
    .filter((row) => ["fabric", "semi_finished", ""].includes(row.item?.category?.toLowerCase() || ""))
    .slice()
    .sort((a, b) => Number(b.material_role === "main") - Number(a.material_role === "main") || a.id - b.id);
  const variantUrl = materialImage?.file_url || fabrics.map((row) => row.photo_url || row.item?.image_url).find(Boolean);
  const identity = modelOrderLabel(model);
  const emptyLabel = isLoading ? t("common.loading") : t("page.workOrder.noImage");

  if (error) return <p className="mt-2 text-xs text-red-700" role="status">{t("page.modelDetail.loadError")}</p>;

  return (
    <div className="mt-2 flex gap-3" aria-busy={isLoading}>
      {[
        { label: t("field.model"), url: modelImage?.file_url },
        { label: t("page.modelDetail.variant"), url: variantUrl },
        ...(images.some((image) => image.image_type === "print")
          ? [{ label: t("page.modelDetail.printPicture"), url: images.find((image) => image.image_type === "print")?.file_url }] : []),
      ].map(({ label, url }) => (
        <div key={label} className="w-20 shrink-0">
          <div className="mb-1 text-xs text-[#8a8472]">{label}</div>
          {url ? (
            <a
              href={imagePreviewHref(url, `${label}: ${identity}`)}
              target="_blank"
              rel="noopener noreferrer"
              title={`${label}: ${identity}`}
              className="flex h-20 w-20 items-center justify-center overflow-hidden rounded-md border border-[#ded9ca] bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c2410c]"
            >
              <img src={storageThumbnailUrl(url, 160)} alt={`${label}: ${identity}`} className="h-full w-full object-contain" loading="lazy" />
            </a>
          ) : (
            <div className="flex h-20 w-20 flex-col items-center justify-center gap-1 rounded-md border border-[#ded9ca] bg-[#f4f1e8] px-1 text-center text-xs text-[#8a8472]" aria-label={`${label}: ${emptyLabel}`}>
              <ImageIcon className="h-4 w-4" aria-hidden="true" />
              <span>{emptyLabel}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
