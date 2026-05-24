type BrandMarkProps = {
  size?: number;
  className?: string;
};

export default function BrandMark({ size = 36, className = "" }: BrandMarkProps) {
  return (
    <div
      className={`grid place-items-center overflow-hidden rounded-lg bg-transparent ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <img
        src="/branding/font_A_mark.svg"
        alt=""
        className="h-full w-full object-contain"
      />
    </div>
  );
}
