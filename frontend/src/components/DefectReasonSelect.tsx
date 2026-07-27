"use client";

import { defectReasonOptions } from "@/lib/defectReasons";
import { useT } from "@/lib/i18n";

type DefectReasonSelectProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
};

export default function DefectReasonSelect({
  id,
  value,
  onChange,
  required = false,
}: DefectReasonSelectProps) {
  const { t } = useT();

  return (
    <select
      id={id}
      className="input"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      required={required}
    >
      <option value="">{t("field.selectDefectReason")}</option>
      {defectReasonOptions(t).map((reason) => (
        <option key={reason.value} value={reason.value}>
          {reason.label}
        </option>
      ))}
    </select>
  );
}
