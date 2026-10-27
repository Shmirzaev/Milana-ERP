"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type Confirmation = { version: number; done: boolean; handed_over: boolean; items: { size: string; quantity: number }[] };
const labels = {
  en: { title: "Confirm packaged quantities", save: "Save quantities", done: "Mark as done", edit: "Edit quantities", completed: "Packaging completed", size: "Size", quantity: "Quantity" },
  ru: { title: "Подтверждение количества упаковки", save: "Сохранить количество", done: "Отметить готовым", edit: "Изменить количество", completed: "Упаковка завершена", size: "Размер", quantity: "Количество" },
  uz: { title: "Qadoqlangan miqdorni tasdiqlash", save: "Miqdorni saqlash", done: "Tugallandi deb belgilash", edit: "Miqdorni tahrirlash", completed: "Qadoqlash tugallandi", size: "O‘lcham", quantity: "Miqdor" },
};

export default function UslugaPackaging({ workOrderId, onSaved }: { workOrderId: number; onSaved: () => Promise<void> }) {
  const { lang, t } = useT();
  const c = labels[lang];
  const { data, error, mutate } = useSWR<Confirmation>(`/api/work-orders/${workOrderId}/usluga-packaging`, fetcher);
  const [draft, setDraft] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const value = draft || data;
  async function save(done: boolean) {
    if (!value || busy) return;
    setBusy(true); setActionError("");
    try {
      const result = await api.put<Confirmation>(`/api/work-orders/${workOrderId}/usluga-packaging`, { version: value.version, items: value.items, done });
      await mutate(result, false); setDraft(null); await onSaved();
    } catch (e: unknown) { setActionError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return <section className="card max-w-3xl p-4">
    <h2 className="mb-4 text-base font-semibold">{c.title}</h2>
    {(actionError || error) && <p role="alert" className="mb-3 text-red-700">{actionError || error.message}</p>}
    {!value ? <p>{t("common.loading")}</p> : <>
      {value.done && !draft && <p className="mb-3" role="status">{c.completed}</p>}
      <table className="table"><thead><tr><th>{c.size}</th><th>{c.quantity}</th></tr></thead><tbody>
        {value.items.map((row, index) => <tr key={row.size}><td>{row.size}</td><td><input aria-label={`${c.quantity} ${row.size}`} className="input max-w-40" type="number" min={0} step={1}
          disabled={busy || value.handed_over || (value.done && !draft)} value={row.quantity}
          onChange={event => setDraft({ ...value, items: value.items.map((item, i) => i === index ? { ...item, quantity: Number(event.target.value) } : item) })} /></td></tr>)}
      </tbody></table>
      {!value.handed_over && <div className="mt-4 flex flex-wrap gap-2">
        {value.done && !draft ? <button className="btn" onClick={() => setDraft({ ...value })}>{c.edit}</button> : <>
          <button className="btn" disabled={busy} onClick={() => void save(false)}>{c.save}</button>
          <button className="btn btn-primary" disabled={busy} onClick={() => void save(true)}>{c.done}</button>
        </>}
      </div>}
    </>}
  </section>;
}
