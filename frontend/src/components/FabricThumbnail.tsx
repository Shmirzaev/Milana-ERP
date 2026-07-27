"use client";

import Link from "next/link";
import { ImageIcon } from "lucide-react";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { useT } from "@/lib/i18n";

export default function FabricThumbnail({
  imageUrl,
  label,
  size = "md",
}: {
  imageUrl?: string | null;
  label?: string | null;
  size?: "sm" | "md";
}) {
  const { t } = useT();
  const src = storageThumbnailUrl(imageUrl, 160);
  const dimensions = size === "sm" ? "h-11 w-11" : "h-14 w-14";
  const alt = label || t("page.workOrder.materialPicture");

  if (!src) {
    return (
      <div
        className={`${dimensions} flex shrink-0 items-center justify-center rounded-md border border-[#ded9ca] bg-[#f4f1e8] text-[#9a927f]`}
        title={t("page.workOrder.noImage")}
        aria-label={t("page.workOrder.noImage")}
      >
        <ImageIcon className="h-4 w-4" aria-hidden="true" />
      </div>
    );
  }

  return (
    <Link
      href={imagePreviewHref(imageUrl, alt)}
      target="_blank"
      rel="noreferrer"
      className={`${dimensions} block shrink-0 overflow-hidden rounded-md border border-[#ded9ca] bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c2410c]`}
      title={t("page.workOrder.materialPicture")}
    >
      <img src={src} alt={alt} className="h-full w-full object-cover" loading="lazy" />
    </Link>
  );
}
