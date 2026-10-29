"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const text = {
  en: { edit: "Change factory", hint: "Choose the whole order or individual Nastils. Unused line assignments for the selected work will be released.", whole: "Whole order", selected: "Selected Nastils", saved: "Sewing factory updated." },
  ru: { edit: "Изменить фабрику", hint: "Выберите весь заказ или отдельные настилы. Неиспользованные назначения выбранной работы на потоки будут сняты.", whole: "Весь заказ", selected: "Выбранные настилы", saved: "Швейная фабрика изменена." },
  uz: { edit: "Fabrikani o‘zgartirish", hint: "Butun buyurtma yoki alohida nastillarni tanlang. Tanlangan ishning ishlatilmagan potok topshiriqlari bekor qilinadi.", whole: "Butun buyurtma", selected: "Tanlangan nastillar", saved: "Tikuv fabrikasi o‘zgartirildi." },
};

export default function CuttingSewingFactory({ workOrderId, factory, locked, batches, onSaved }: {
  workOrderId: number; factory: string; locked: boolean; onSaved: () => Promise<unknown>;
  batches: { id: number; name?: string; batch_no: string; sewing_output_recorded?: boolean; bundle_count: number }[];
}) {
  const { lang, t } = useT();
  const copy = text[lang];
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(factory);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [partial, setPartial] = useState(locked);
  const [batchIds, setBatchIds] = useState<number[]>([]);
  const eligible = batches.filter(batch => !batch.sewing_output_recorded && batch.bundle_count > 0);
  return <section className="card p-4 mb-4">
    <button type="button" className="btn" disabled={busy || (locked && !eligible.length)} aria-expanded={open} onClick={() => { setSelected(factory); setPartial(locked); setBatchIds([]); setOpen(!open); }}>{copy.edit}</button>
    {locked && <p className="mt-2 text-sm">{t("batch.lockedAfterSewing")}</p>}
    {open && <form className="mt-3 space-y-3" onSubmit={async event => {
      event.preventDefault();
      if (busy) return;
      setBusy(true); setMessage("");
      try {
        await api.patch(`/api/work-orders/${workOrderId}/sewing-factory`, { sewing_factory_code: selected, ...(partial ? { production_batch_ids: batchIds } : {}) });
        await onSaved(); setOpen(false); setMessage(copy.saved);
      } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
      finally { setBusy(false); }
    }}>
      <p className="text-sm">{copy.hint}</p>
      <div className="flex gap-4 text-sm">
        <label><input type="radio" name="factory-scope" checked={!partial} disabled={busy || locked} onChange={() => setPartial(false)} /> {copy.whole}</label>
        <label><input type="radio" name="factory-scope" checked={partial} disabled={busy || !eligible.length} onChange={() => setPartial(true)} /> {copy.selected}</label>
      </div>
      {partial && <fieldset className="space-y-2"><legend className="label">{copy.selected}</legend>{batches.map(batch => <label key={batch.id} className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={batchIds.includes(batch.id)} disabled={busy || !eligible.some(row => row.id === batch.id)} onChange={event => setBatchIds(ids => event.target.checked ? [...ids, batch.id] : ids.filter(id => id !== batch.id))} />
        {batch.name || batch.batch_no}{batch.sewing_output_recorded ? ` · ${t("batch.lockedAfterSewing")}` : ""}
      </label>)}</fieldset>}
      <label className="label">{t("field.sewingFactory")}
        <select className="input max-w-xs" aria-label={t("field.sewingFactory")} value={selected} disabled={busy} onChange={event => setSelected(event.target.value)}>
          <option value="MIL">Milana</option><option value="BST">Besttex</option><option value="ECO">Eco Cotton</option>
        </select>
      </label>
      <button className="btn btn-primary" disabled={busy || (partial ? !batchIds.length : locked || selected === factory)}>{t("btn.save")}</button>
    </form>}
    {message && <p role="status" className="mt-2 text-sm">{message}</p>}
  </section>;
}
