"use client";

import { useT } from "@/lib/i18n";
import { parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import type { SizeAllocation } from "@/lib/processQrSizeAllocation";

export default function ProcessQrBatchSizes({ name, allocation, disabled, onChange }: {
  name: string;
  allocation: SizeAllocation;
  disabled: boolean;
  onChange: (size: string, quantity: NumberInputValue) => void;
}) {
  const { t } = useT();
  const assigned = allocation.rows.reduce((sum, row) => sum + Number(row.quantity || 0), 0);
  return <div className="mb-4">
    <h3 className="mb-2 text-sm font-semibold">{name}</h3>
    {allocation.suggested && <p className="mb-3 text-sm text-[#8a8472]">{t("page.processQr.autoSizeSplit")}</p>}
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {allocation.rows.map(row => <label key={row.size}>
        <span className="label">{row.size}</span>
        <input className="input" type="number" min={row.recorded} step={1}
          value={row.quantity} readOnly={!allocation.suggested} disabled={disabled}
          onChange={event => onChange(row.size, parseNumberInput(event.target.value))} />
        {row.recorded > 0 && <span className="mt-1 block text-xs text-[#8a8472]">
          {t("page.processQr.sewingEnteredSizeQty", { quantity: row.recorded })}
        </span>}
      </label>)}
    </div>
    <p className="mt-2 text-sm">{t("page.processQr.sizeSplitTotal", { assigned, total: allocation.total })}</p>
    {!allocation.valid && <p role="alert" className="mt-2 text-sm text-red-700">
      {t(allocation.rows.length ? "page.processQr.sizeSplitInvalid" : "page.processQr.sizeSplitMissing")}
    </p>}
  </div>;
}
