export default function PageHeader({
  title, subtitle, actions, eyebrow,
}: { title: string; subtitle?: string; actions?: React.ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-5 flex min-w-0 flex-col gap-3 sm:mb-6 lg:flex-row lg:items-end lg:justify-between lg:gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-4 text-sm text-[#8a8472]">{eyebrow}</div> : null}
        <h1 className="break-words text-2xl font-semibold leading-tight tracking-tight text-[#14110b] sm:text-[27px]">{title}</h1>
        {subtitle ? <p className="mt-1 max-w-4xl break-words text-sm leading-relaxed text-[#8a8472]">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header-actions flex w-full min-w-0 flex-wrap gap-2 lg:w-auto lg:max-w-[60%] lg:justify-end">{actions}</div> : null}
    </div>
  );
}
