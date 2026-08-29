"use client";

import { Plus, Trash2 } from "lucide-react";
import { useT } from "@/lib/i18n";

export function rollWeightsTotal(values: string[]) {
  return values.reduce((total, value) => {
    const parsed = Number(value);
    return total + (Number.isFinite(parsed) && parsed > 0 ? parsed : 0);
  }, 0);
}

export function validRollWeights(values: string[]) {
  return values.length > 0 && values.every((value) => Number.isFinite(Number(value)) && Number(value) > 0);
}

export default function MaterialRollWeightFields({
  values,
  onChange,
  disabled = false,
}: {
  values: string[];
  onChange: (values: string[]) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  const total = rollWeightsTotal(values);

  return (
    <fieldset className="border-t border-[#ded9ca] pt-3 md:col-span-2" disabled={disabled}>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <legend className="text-sm font-semibold text-[#14110b]">{t("page.inventory.rollWeights")}</legend>
          <div className="mt-0.5 text-xs text-[#6f684f]">{t("page.inventory.rollWeightsHint")}</div>
        </div>
        <button type="button" className="btn shrink-0" onClick={() => onChange([...values, ""])}>
          <Plus className="h-4 w-4" />
          {t("page.inventory.addRoll")}
        </button>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {values.map((value, index) => (
          <div key={index} className="flex items-end gap-2">
            <div className="min-w-0 flex-1">
              <label className="label">{t("page.inventory.rollWeight", { roll: index + 1 })}</label>
              <div className="relative">
                <input
                  className="input pr-10"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  step="0.01"
                  value={value}
                  onChange={(event) => {
                    const next = [...values];
                    next[index] = event.target.value;
                    onChange(next);
                  }}
                  required
                />
                <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-[#6f684f]">kg</span>
              </div>
            </div>
            <button
              type="button"
              className="icon-btn mb-0.5 text-red-700"
              title={t("page.inventory.removeRoll")}
              disabled={values.length <= 1}
              onClick={() => onChange(values.filter((_, valueIndex) => valueIndex !== index))}
            >
              <Trash2 />
            </button>
          </div>
        ))}
      </div>
      <div className="mt-2 text-right text-sm text-[#56503f]">
        {t("page.inventory.rollWeightsTotal")}: <span className="font-semibold text-[#14110b]">{total.toFixed(2)} kg</span>
      </div>
    </fieldset>
  );
}
