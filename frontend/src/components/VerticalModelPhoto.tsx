"use client";

import { useState } from "react";

type VerticalModelPhotoProps = {
  src: string;
  alt: string;
  className?: string;
  loading?: "eager" | "lazy";
  width?: number;
  height?: number;
};

export default function VerticalModelPhoto({
  src,
  alt,
  className = "",
  loading = "lazy",
  width = 240,
  height = 320,
}: VerticalModelPhotoProps) {
  const [isLandscape, setIsLandscape] = useState<boolean | null>(null);

  return (
    <span className={`relative block aspect-[3/4] overflow-hidden bg-[#f1efe8] ${className}`}>
      <img
        src={src}
        alt={alt}
        className={
          isLandscape
            ? "absolute left-1/2 top-1/2 h-[75%] w-[133.333%] max-w-none -translate-x-1/2 -translate-y-1/2 rotate-90 object-cover"
            : "h-full w-full object-cover"
        }
        loading={loading}
        decoding="async"
        width={width}
        height={height}
        onLoad={(event) => {
          const image = event.currentTarget;
          setIsLandscape(image.naturalWidth > image.naturalHeight);
        }}
      />
    </span>
  );
}
