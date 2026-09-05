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
  return (
    <span className={`relative block aspect-[3/4] overflow-hidden bg-[#f1efe8] p-1 ${className}`}>
      <img
        src={src}
        alt={alt}
        className="h-full w-full object-contain"
        loading={loading}
        decoding="async"
        width={width}
        height={height}
      />
    </span>
  );
}
