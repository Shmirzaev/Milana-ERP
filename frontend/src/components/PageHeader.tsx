export default function PageHeader({
  title, subtitle, actions, eyebrow,
}: { title: string; subtitle?: string; actions?: React.ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:mb-6 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-4 text-sm text-[#8a8472]">{eyebrow}</div> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-[#14110b] sm:truncate sm:text-[27px]">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-[#8a8472]">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex w-full shrink-0 flex-wrap gap-2 sm:w-auto sm:justify-end">{actions}</div> : null}
    </div>
  );
}
