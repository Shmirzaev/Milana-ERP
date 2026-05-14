export default function PageHeader({
  title, subtitle, actions, eyebrow,
}: { title: string; subtitle?: string; actions?: React.ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-4 text-sm text-[#8a8472]">{eyebrow}</div> : null}
        <h1 className="truncate text-[27px] font-semibold tracking-tight text-[#14110b]">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-[#8a8472]">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap justify-end gap-2">{actions}</div> : null}
    </div>
  );
}
