type VerticalModelPhotoProps = {
  src: string;
  alt: string;
  className?: string;
  loading?: "eager" | "lazy";
  width?: number;
  height?: number;
  adaptiveHeight?: boolean;
};

export default function VerticalModelPhoto({
  src,
  alt,
  className = "",
  loading = "lazy",
  width = 240,
  height = 320,
  adaptiveHeight = false,
}: VerticalModelPhotoProps) {
  return (
    <span
      className={`relative flex w-full items-center justify-center overflow-hidden bg-[#f1efe8] p-1 ${adaptiveHeight ? "" : "aspect-[3/4]"} ${className}`}
    >
      <img
        src={src}
        alt={alt}
        className={adaptiveHeight ? "block h-auto max-h-40 w-full object-contain" : "h-full w-full object-contain"}
        loading={loading}
        decoding="async"
        width={width}
        height={height}
      />
    </span>
  );
}
