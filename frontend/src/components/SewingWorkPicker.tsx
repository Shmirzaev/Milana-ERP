"use client";

import { useMemo, useState } from "react";
import { Check, ChevronDown, ImageIcon } from "lucide-react";

import { formatBatchLabel } from "@/lib/batchSerial";
import { useT } from "@/lib/i18n";
import { storageThumbnailUrl } from "@/lib/modelImages";

export type SewingModelIdentity = {
  model_id?: number | null;
  model_code?: string | null;
  model_no?: string | null;
  variant_no?: string | null;
  model_name?: string | null;
  model_image_url?: string | null;
  fabric_image_url?: string | null;
};

export type SewingWorkOption = SewingModelIdentity & {
  work_order_id: number;
  sewing_assignment_id: number | null;
  production_order_id: number;
  production_batch_id: number | null;
  batch_no?: string | null;
  batch_name?: string | null;
  batch_index?: number | null;
  remaining_qty: number;
};

export function sewingWorkKey(work: Pick<SewingWorkOption, "work_order_id" | "sewing_assignment_id">) {
  return `${work.work_order_id}:${work.sewing_assignment_id ?? ""}`;
}

function batchLabel(work: SewingWorkOption) {
  if (!work.production_batch_id) return "";
  return formatBatchLabel(
    {
      batch_no: work.batch_no,
      name: work.batch_name,
      batch_index: work.batch_index,
    },
    work.production_order_id,
  );
}

function ModelThumbnail({ model, small = false }: { model: SewingModelIdentity; small?: boolean }) {
  const src = storageThumbnailUrl(model.fabric_image_url, 160);
  const size = small ? "h-9 w-9" : "h-11 w-11";
  if (!src) {
    return (
      <div className={`${size} flex shrink-0 items-center justify-center rounded-md border border-[#ded9ca] bg-[#f4f1e8] text-[#9a927f]`}>
        <ImageIcon className="h-4 w-4" aria-hidden="true" />
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={model.model_no || model.model_code || model.model_name || "Model"}
      className={`${size} shrink-0 rounded-md border border-[#ded9ca] bg-white object-cover`}
      loading="lazy"
    />
  );
}

export function SewingModelCell({ model, small = true }: { model: SewingModelIdentity; small?: boolean }) {
  const { t } = useT();
  const modelNumber = model.model_no || model.model_code || "-";
  return (
    <div className="flex min-w-[170px] items-center gap-2">
      <ModelThumbnail model={model} small={small} />
      <div className="min-w-0">
        <div className="font-semibold text-[#14110b]">{modelNumber}</div>
        <div className="text-xs text-[#6b6251]">
          {t("field.variantNo")}: <span className="font-medium text-[#14110b]">{model.variant_no || "-"}</span>
        </div>
        {model.model_name && <div className="truncate text-[11px] text-[#8a8472]">{model.model_name}</div>}
      </div>
    </div>
  );
}

export default function SewingWorkPicker({
  options,
  value,
  onChange,
}: {
  options: SewingWorkOption[];
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const selected = useMemo(
    () => options.find((work) => sewingWorkKey(work) === value) || options[0] || null,
    [options, value],
  );

  if (!selected) return null;

  return (
    <div>
      <button
        type="button"
        className="flex w-full items-center gap-3 rounded-md border border-[#ded9ca] bg-white px-2.5 py-2 text-left shadow-sm transition-colors hover:border-[#c9c1ae] focus:outline-none focus:ring-2 focus:ring-[#c2410c]/20"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        <ModelThumbnail model={selected} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-semibold text-[#14110b]">{selected.model_no || selected.model_code || "-"}</span>
            <span className="text-sm text-[#56503f]">{t("field.variantNo")}: {selected.variant_no || "-"}</span>
          </div>
          <div className="mt-0.5 truncate text-xs text-[#8a8472]">
            {[batchLabel(selected), `${selected.remaining_qty} ${t("field.remaining").toLowerCase()}`].filter(Boolean).join(" · ")}
          </div>
        </div>
        <ChevronDown className={`h-4 w-4 shrink-0 text-[#8a8472] transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="mt-1 max-h-64 overflow-y-auto rounded-md border border-[#ded9ca] bg-white p-1 shadow-sm">
          {options.map((work) => {
            const key = sewingWorkKey(work);
            const active = key === sewingWorkKey(selected);
            return (
              <button
                key={key}
                type="button"
                className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left transition-colors ${active ? "bg-[#f1efe8]" : "hover:bg-[#f8f6ef]"}`}
                onClick={() => {
                  onChange(key);
                  setOpen(false);
                }}
              >
                <ModelThumbnail model={work} small />
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-[#14110b]">
                    {work.model_no || work.model_code || "-"}
                    <span className="ml-2 font-normal text-[#56503f]">{t("field.variantNo")}: {work.variant_no || "-"}</span>
                  </div>
                  <div className="truncate text-xs text-[#8a8472]">
                    {[work.model_name, batchLabel(work), `${work.remaining_qty} ${t("field.remaining").toLowerCase()}`].filter(Boolean).join(" · ")}
                  </div>
                </div>
                <Check className={`h-4 w-4 shrink-0 ${active ? "text-[#14110b]" : "text-transparent"}`} />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
