"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const text = {
  en: { edit: "Edit sewing factory", hint: "Changes the destination for this whole order before Sewing output. Unused line assignments will be released.", saved: "Sewing factory updated." },
  ru: { edit: "Изменить швейную фабрику", hint: "Меняет фабрику для всего заказа до ввода выхода пошива. Неиспользованные назначения на потоки будут сняты.", saved: "Швейная фабрика изменена." },
  uz: { edit: "Tikuv fabrikasini o‘zgartirish", hint: "Tikuv chiqimi kiritilguncha butun buyurtma fabrikasini o‘zgartiradi. Ishlatilmagan potok topshiriqlari bekor qilinadi.", saved: "Tikuv fabrikasi o‘zgartirildi." },
};

export default function CuttingSewingFactory({ workOrderId, factory, locked, onSaved }: {
  workOrderId: number; factory: string; locked: boolean; onSaved: () => Promise<unknown>;
}) {
  const { lang, t } = useT();
  const copy = text[lang];
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(factory);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return <section className="card p-4 mb-4">
    <button type="button" className="btn" disabled={locked || busy} aria-expanded={open} onClick={() => { setSelected(factory); setOpen(!open); }}>{copy.edit}</button>
    {locked && <p className="mt-2 text-sm">{t("batch.lockedAfterSewing")}</p>}
    {open && !locked && <form className="mt-3 space-y-3" onSubmit={async event => {
      event.preventDefault();
      if (busy) return;
      setBusy(true); setMessage("");
      try {
        await api.patch(`/api/work-orders/${workOrderId}/sewing-factory`, { sewing_factory_code: selected });
        await onSaved(); setOpen(false); setMessage(copy.saved);
      } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
      finally { setBusy(false); }
    }}>
      <p className="text-sm">{copy.hint}</p>
      <label className="label">{t("field.sewingFactory")}
        <select className="input max-w-xs" aria-label={t("field.sewingFactory")} value={selected} disabled={busy} onChange={event => setSelected(event.target.value)}>
          <option value="MIL">Milana</option><option value="BST">Besttex</option><option value="ECO">Eco Cotton</option>
        </select>
      </label>
      <button className="btn btn-primary" disabled={busy || selected === factory}>{t("btn.save")}</button>
    </form>}
    {message && <p role="status" className="mt-2 text-sm">{message}</p>}
  </section>;
}
