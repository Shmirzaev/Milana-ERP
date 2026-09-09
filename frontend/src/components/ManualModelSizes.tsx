"use client";

import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { GARMENT_SIZE_OPTIONS, garmentSizeRange, garmentSizeRangeEndOptions } from "@/lib/garmentSizes";

const COPY = {
  en: {
    title: "Add model sizes", help: "Choose the first and last size. All sizes in between are included automatically and saved to this model variant.",
    save: "Save sizes to model", saved: "Sizes saved to model.", invalid: "Choose a valid size range.",
    conflict: "This model already has sizes. Refresh to use the saved sizes.", denied: "You do not have permission to add model sizes.",
    failed: "Could not save sizes. Please try again.",
  },
  ru: {
    title: "Добавить размеры модели", help: "Выберите первый и последний размер. Все промежуточные размеры добавляются автоматически и сохраняются в этом варианте модели.",
    save: "Сохранить размеры в модели", saved: "Размеры сохранены в модели.", invalid: "Выберите корректный диапазон размеров.",
    conflict: "У модели уже есть размеры. Обновите страницу, чтобы загрузить их.", denied: "У вас нет разрешения добавлять размеры модели.",
    failed: "Не удалось сохранить размеры. Попробуйте ещё раз.",
  },
  uz: {
    title: "Model o‘lchamlarini qo‘shish", help: "Boshlang‘ich va oxirgi o‘lchamni tanlang. Oradagi barcha o‘lchamlar avtomatik qo‘shiladi va shu model variantiga saqlanadi.",
    save: "O‘lchamlarni modelga saqlash", saved: "O‘lchamlar modelga saqlandi.", invalid: "To‘g‘ri o‘lcham oralig‘ini tanlang.",
    conflict: "Bu modelda o‘lchamlar allaqachon mavjud. Ularni yuklash uchun sahifani yangilang.", denied: "Model o‘lchamlarini qo‘shishga ruxsatingiz yo‘q.",
    failed: "O‘lchamlarni saqlab bo‘lmadi. Qayta urinib ko‘ring.",
  },
};

export type SavedModelSizes = { model_id: number; sizes: string[]; resolution: "own" };
type Props = { modelId: number; onSaved: (result: SavedModelSizes) => void };

function ModelSizeEditor({ modelId, onSaved }: Props) {
  const { lang, t } = useT();
  const { me } = useMe();
  const copy = COPY[lang];
  const inputId = useId();
  const [sizeFrom, setSizeFrom] = useState("46");
  const [sizeTo, setSizeTo] = useState("56");
  const endOptions = garmentSizeRangeEndOptions(sizeFrom);
  const sizes = garmentSizeRange(sizeFrom, sizeTo);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<"invalid" | "conflict" | "denied" | "failed" | null>(null);
  const savingRef = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  async function save() {
    if (savingRef.current || saved) return;
    if (!sizes.length) {
      setError("invalid");
      return;
    }
    savingRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<SavedModelSizes>(`/api/models/${modelId}/process-qr-sizes`, { sizes });
      if (!mountedRef.current) return;
      setSaved(true);
      onSaved(result);
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      const message = err instanceof Error ? err.message : "";
      setError(message.startsWith("409:") ? "conflict" : message.startsWith("403:") ? "denied" : message.startsWith("422:") ? "invalid" : "failed");
    } finally {
      savingRef.current = false;
      if (mountedRef.current) setBusy(false);
    }
  }

  if (!can(me, "payroll.manage", "modeling.models")) return null;
  return (
    <div className="space-y-2 border-t border-[#e3dfd3] pt-4">
      <div className="text-sm font-semibold">{copy.title}</div>
      <p id={`${inputId}-help`} className="text-xs text-[#8a8472]">{copy.help}</p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <div>
          <label htmlFor={`${inputId}-from`} className="label">{t("newso.sizeFrom")}</label>
          <select id={`${inputId}-from`} aria-describedby={`${inputId}-help`} className="input w-full" value={sizeFrom} onChange={(event) => {
            const next = event.target.value;
            setSizeFrom(next);
            if (!garmentSizeRangeEndOptions(next).includes(sizeTo)) setSizeTo(next);
            setError(null);
          }} disabled={busy || saved}>
            {GARMENT_SIZE_OPTIONS.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={`${inputId}-to`} className="label">{t("newso.sizeTo")}</label>
          <select id={`${inputId}-to`} aria-describedby={`${inputId}-help`} className="input w-full" value={sizeTo} onChange={(event) => { setSizeTo(event.target.value); setError(null); }} disabled={busy || saved}>
            {endOptions.map((size) => <option key={size} value={size}>{size}</option>)}
          </select>
        </div>
      </div>
      <p role="status" className="text-sm">{t("page.modelDetail.sizeRange")} {sizes.join(", ")}</p>
      {error ? <p role="alert" className="text-sm text-red-700">{copy[error]}</p> : null}
      {saved ? <p role="status" className="text-sm text-green-800">{copy.saved}</p> : <button type="button" className="btn" onClick={() => void save()} disabled={busy || !sizes.length}>{busy ? t("common.loading") : copy.save}</button>}
    </div>
  );
}

export default function ManualModelSizes(props: Props) {
  // Reset unsaved input and isolate late responses when the variant changes.
  return <ModelSizeEditor key={props.modelId} {...props} />;
}
