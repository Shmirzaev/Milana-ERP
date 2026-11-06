"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { useT } from "@/lib/i18n";
import { MATERIAL_COLOR_OPTIONS } from "@/lib/materialColors";

const COPY = {
  en: { add: "Add color", name: "Color name", choose: "Choose color" },
  ru: { add: "Добавить цвет", name: "Название цвета", choose: "Выбрать цвет" },
  uz: { add: "Rang qo‘shish", name: "Rang nomi", choose: "Rang tanlash" },
};

export default function VariantColorSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t, lang } = useT();
  const [custom, setCustom] = useState(false);
  const known = MATERIAL_COLOR_OPTIONS.some(option => option.value === value);
  return <div className="space-y-1">
    {custom ? <input id="variant-material-color" className="input" value={value} maxLength={64}
      aria-label={COPY[lang].name} placeholder={COPY[lang].name} autoFocus
      onChange={event => onChange(event.target.value)} /> :
      <select id="variant-material-color" className="input" value={value} onChange={event => onChange(event.target.value)}>
        <option value="">{t("page.receiveStock.selectMaterialColor")}</option>
        {value && !known && <option value={value}>{value}</option>}
        {MATERIAL_COLOR_OPTIONS.map(option => <option key={option.value} value={option.value}>{t(option.labelKey)}</option>)}
      </select>}
    <button type="button" className="btn text-sm" onClick={() => { setCustom(!custom); if (!custom) onChange(""); }}>
      {!custom && <Plus className="h-4 w-4" />}{custom ? COPY[lang].choose : COPY[lang].add}
    </button>
  </div>;
}
