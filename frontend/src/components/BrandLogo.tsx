type BrandLogoProps = {
  alt: string;
  className?: string;
};

export default function BrandLogo({ alt, className = "" }: BrandLogoProps) {
  return (
    <img
      src="/branding/font_A_inter.svg"
      alt={alt}
      className={`object-contain object-left select-none ${className}`}
      draggable={false}
    />
  );
}
