"use client";

import { Pencil } from "lucide-react";

import { useT } from "@/lib/i18n";

export type ManualModelIdentityValue = {
  enabled: boolean;
  modelNo: string;
  variantNo: string;
};

export default function ManualModelIdentityFields({
  value,
  onChange,
  inputIdPrefix,
  alwaysVisible = false,
  modelNoRequired = false,
}: {
  value: ManualModelIdentityValue;
  onChange: (value: ManualModelIdentityValue) => void;
  inputIdPrefix: string;
  alwaysVisible?: boolean;
  modelNoRequired?: boolean;
}) {
  const { t } = useT();

  if (!value.enabled && !alwaysVisible) {
    return (
      <button
        type="button"
        className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-[#56503f] underline decoration-[#c9c1ae] underline-offset-4 hover:text-[#14110b]"
        onClick={() => onChange({
          enabled: true,
          modelNo: value.modelNo,
          variantNo: value.variantNo,
        })}
      >
        <Pencil className="h-3.5 w-3.5" />
        {t("page.sewingDailyReport.enterModelManually")}
      </button>
    );
  }

  return (
    <div className="mt-2 border-t border-[#e3dfd3] pt-2">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-xs text-[#56503f]" htmlFor={`${inputIdPrefix}-model-no`}>
            {t("field.modelNo")}
          </label>
          <input
            id={`${inputIdPrefix}-model-no`}
            className="input"
            value={value.modelNo}
            maxLength={64}
            required={modelNoRequired}
            onChange={(event) => onChange({ ...value, enabled: true, modelNo: event.target.value })}
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-[#56503f]" htmlFor={`${inputIdPrefix}-variant-no`}>
            {t("field.variantNo")}
          </label>
          <input
            id={`${inputIdPrefix}-variant-no`}
            className="input"
            value={value.variantNo}
            maxLength={64}
            onChange={(event) => onChange({ ...value, enabled: true, variantNo: event.target.value })}
          />
        </div>
      </div>
      {!alwaysVisible && (
        <button
          type="button"
          className="mt-2 text-xs font-medium text-[#56503f] underline decoration-[#c9c1ae] underline-offset-4 hover:text-[#14110b]"
          onClick={() => onChange({ enabled: false, modelNo: "", variantNo: "" })}
        >
          {t("common.cancel")}
        </button>
      )}
    </div>
  );
}
