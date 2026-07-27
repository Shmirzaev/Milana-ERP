type BrandLogoProps = {
  alt: string;
  className?: string;
  markOnly?: boolean;
};

export default function BrandLogo({ alt, className = "", markOnly = false }: BrandLogoProps) {
  return (
    <img
      src={markOnly ? "/branding/font_A_mark.svg" : "/branding/font_A_inter.svg"}
      alt={alt}
      className={`object-contain object-left select-none ${className}`}
      draggable={false}
    />
  );
}
