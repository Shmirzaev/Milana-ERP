"use client";

import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

const COPY = {
  en: {
    title: "Add model sizes", help: "Separate sizes with commas or new lines. These sizes are saved to this model variant.",
    save: "Save sizes to model", saved: "Sizes saved to model.", invalid: "Enter 1–40 unique sizes, up to 32 characters each.",
    conflict: "This model already has sizes. Refresh to use the saved sizes.", denied: "You do not have permission to add model sizes.",
    failed: "Could not save sizes. Please try again.",
  },
  ru: {
    title: "Добавить размеры модели", help: "Разделяйте размеры запятыми или переносами строк. Размеры сохраняются в этом варианте модели.",
    save: "Сохранить размеры в модели", saved: "Размеры сохранены в модели.", invalid: "Введите от 1 до 40 уникальных размеров, не более 32 символов каждый.",
    conflict: "У модели уже есть размеры. Обновите страницу, чтобы загрузить их.", denied: "У вас нет разрешения добавлять размеры модели.",
    failed: "Не удалось сохранить размеры. Попробуйте ещё раз.",
  },
  uz: {
    title: "Model o‘lchamlarini qo‘shish", help: "O‘lchamlarni vergul yoki yangi qator bilan ajrating. Ular shu model variantiga saqlanadi.",
    save: "O‘lchamlarni modelga saqlash", saved: "O‘lchamlar modelga saqlandi.", invalid: "Har biri 32 belgigacha bo‘lgan 1–40 ta takrorlanmagan o‘lcham kiriting.",
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
  const [value, setValue] = useState("");
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
    const sizes = value.split(/[,;\r\n]+/).map((size) => size.trim()).filter(Boolean);
    if (!sizes.length || sizes.length > 40 || sizes.some((size) => size.length > 32) || new Set(sizes.map((size) => size.toLocaleLowerCase())).size !== sizes.length) {
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
      <label htmlFor={inputId} className="block text-sm font-semibold">{copy.title}</label>
      <p id={`${inputId}-help`} className="text-xs text-[#8a8472]">{copy.help}</p>
      <textarea id={inputId} aria-describedby={`${inputId}-help`} className="input min-h-20 w-full" value={value} onChange={(event) => { setValue(event.target.value); setError(null); }} placeholder="48, 50, 52, 54" disabled={busy || saved} />
      {error ? <p role="alert" className="text-sm text-red-700">{copy[error]}</p> : null}
      {saved ? <p role="status" className="text-sm text-green-800">{copy.saved}</p> : <button type="button" className="btn" onClick={() => void save()} disabled={busy || !value.trim()}>{busy ? t("common.loading") : copy.save}</button>}
    </div>
  );
}

export default function ManualModelSizes(props: Props) {
  // Reset unsaved input and isolate late responses when the variant changes.
  return <ModelSizeEditor key={props.modelId} {...props} />;
}
