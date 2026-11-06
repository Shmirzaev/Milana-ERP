"use client";

import { useState } from "react";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";

export type ProcessQrSizeEdit = { size: string; originalSize: string | null };

const COPY = {
  en: { edit: "Edit sizes", help: "Sizes apply to these manual-order labels. Each edited row keeps its quantity.", add: "Add size", invalid: "Enter different, non-empty sizes (up to 32 characters). Sizes must also have distinct QR codes." },
  ru: { edit: "Изменить размеры", help: "Размеры применяются к этим ярлыкам ручного заказа. Количество в каждой изменённой строке сохраняется.", add: "Добавить размер", invalid: "Укажите разные непустые размеры (до 32 символов). Их QR-коды также должны различаться." },
  uz: { edit: "O‘lchamlarni tahrirlash", help: "O‘lchamlar shu qo‘lda buyurtma yorliqlariga qo‘llanadi. Tahrirlangan har bir qatordagi miqdor saqlanadi.", add: "O‘lcham qo‘shish", invalid: "Takrorlanmaydigan o‘lchamlarni kiriting (32 belgigacha). Ularning QR kodlari ham farqli bo‘lishi kerak." },
};

export default function ProcessQrSizeEditor({ sizes, sizeToken, onApply }: {
  sizes: string[];
  sizeToken: (size: string) => string;
  onApply: (rows: ProcessQrSizeEdit[]) => void;
}) {
  const { lang, t } = useT();
  const copy = COPY[lang];
  const [rows, setRows] = useState<ProcessQrSizeEdit[] | null>(null);
  const cleaned = (rows || []).map((row) => ({ ...row, size: row.size.trim() }));
  const tokens = cleaned.map((row) => sizeToken(row.size));
  const valid = cleaned.length > 0 && cleaned.every((row) => row.size.length > 0 && row.size.length <= 32)
    && tokens.every((token) => token && token !== "-") && new Set(tokens).size === tokens.length;
  return <>
    <button type="button" className="btn mb-4" onClick={() => setRows(sizes.length
      ? sizes.map((size) => ({ size, originalSize: size })) : [{ size: "", originalSize: null }])}>{copy.edit}</button>
    <Modal open={rows !== null} onClose={() => setRows(null)} title={copy.edit}>
      <p className="mb-4 text-sm">{copy.help}</p>
      <div className="space-y-3">
        {(rows || []).map((row, index) => <div key={index} className="flex items-end gap-2">
          <label className="min-w-0 flex-1"><span className="label">{t("field.size")} {index + 1}</span>
            <input className="input" value={row.size} maxLength={32} onChange={(event) => {
              const size = event.target.value;
              setRows((current) => current?.map((entry, i) => i === index ? { ...entry, size } : entry) || null);
            }} />
          </label>
          <button type="button" className="btn" onClick={() => setRows((current) => current?.filter((_, i) => i !== index) || [])}>{t("btn.delete")}</button>
        </div>)}
      </div>
      <button type="button" className="btn mt-3" onClick={() => setRows((current) => [...(current || []), { size: "", originalSize: null }])}>{copy.add}</button>
      {!valid && <p role="alert" className="mt-3 text-sm text-red-700">{copy.invalid}</p>}
      <div className="mt-4 flex gap-2">
        <button type="button" className="btn btn-primary" disabled={!valid} onClick={() => { onApply(cleaned); setRows(null); }}>{t("btn.save")}</button>
        <button type="button" className="btn" onClick={() => setRows(null)}>{t("btn.cancel")}</button>
      </div>
    </Modal>
  </>;
}
