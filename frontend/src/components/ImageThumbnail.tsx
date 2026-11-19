"use client";

import Link from "next/link";
import { ImageIcon } from "lucide-react";
import { useState } from "react";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";

export default function ImageThumbnail({
  imageUrl,
  label,
  title,
  emptyLabel,
  fit = "cover",
}: {
  imageUrl?: string | null;
  label: string;
  title: string;
  emptyLabel: string;
  fit?: "cover" | "contain";
}) {
  const src = storageThumbnailUrl(imageUrl, 160);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  if (!src || failedSrc === src) {
    return (
      <div
        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-[#ded9ca] bg-[#f4f1e8] text-[#9a927f]"
        title={emptyLabel}
        aria-label={`${title}: ${emptyLabel}`}
      >
        <ImageIcon className="h-4 w-4" aria-hidden="true" />
      </div>
    );
  }

  return (
    <Link
      href={imagePreviewHref(imageUrl, label)}
      target="_blank"
      rel="noreferrer"
      className="block h-12 w-12 shrink-0 overflow-hidden rounded-md border border-[#ded9ca] bg-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#c2410c]"
      title={title}
    >
      <img src={src} alt={label} className={`h-full w-full ${fit === "contain" ? "object-contain" : "object-cover"}`} loading="lazy" onError={() => setFailedSrc(src)} />
    </Link>
  );
}
