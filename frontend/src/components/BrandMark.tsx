type BrandMarkProps = {
  size?: number;
  className?: string;
};

export default function BrandMark({ size = 36, className = "" }: BrandMarkProps) {
  return (
    <div
      className={`grid place-items-center rounded-lg bg-[#14110b] text-[#fdfcf8] shadow-sm ring-2 ring-[#ded9ca] ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <span className="text-[11px] font-semibold tracking-[0.12em]">ME</span>
    </div>
  );
}
