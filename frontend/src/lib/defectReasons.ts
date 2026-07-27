import type { CtxT } from "@/lib/i18n";

const DEFECT_REASONS = [
  { value: "hole_present", labelKey: "defectReason.holePresent" },
  { value: "paint_stain_present", labelKey: "defectReason.paintStainPresent" },
  { value: "cut_or_damaged", labelKey: "defectReason.cutOrDamaged" },
  { value: "shorter_than_specified", labelKey: "defectReason.shorterThanSpecified" },
] as const;

const labelKeyByValue = new Map<string, string>(
  DEFECT_REASONS.map((reason) => [reason.value, reason.labelKey]),
);

export function defectReasonOptions(t: CtxT) {
  return DEFECT_REASONS.map((reason) => ({
    value: reason.value,
    label: t(reason.labelKey),
  }));
}

export function defectReasonLabel(value: string | null | undefined, t: CtxT) {
  if (!value) return "-";
  const labelKey = labelKeyByValue.get(value);
  return labelKey ? t(labelKey) : value;
}
