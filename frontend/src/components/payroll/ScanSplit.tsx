"use client";

import { useState } from "react";
import Modal from "@/components/Modal";
import PayrollEmployeeSearch, { type PayrollSearchEmployee } from "@/components/PayrollEmployeeSearch";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

export const scanAllocationText = {
  en: { split: "Split pieces", parts: "Number of parts", pieces: "Pieces", employee: "Employee", save: "Split and credit employees", cancel: "Cancel", total: "Allocated", hint: "The original entry is replaced by these allocations. No printing or rescanning is needed.", workDate: "Work date", previous: "Scans will count toward the selected date, including its payroll month.", saved: "Pieces credited to the selected employees." },
  ru: { split: "Разделить количество", parts: "Количество частей", pieces: "Штук", employee: "Сотрудник", save: "Разделить и начислить сотрудникам", cancel: "Отмена", total: "Распределено", hint: "Исходная запись заменяется этим распределением. Печать и повторное сканирование не нужны.", workDate: "Дата работы", previous: "Сканирования учитываются на выбранную дату и в соответствующем месяце зарплаты.", saved: "Количество начислено выбранным сотрудникам." },
  uz: { split: "Donalarni bo‘lish", parts: "Qismlar soni", pieces: "Dona", employee: "Xodim", save: "Bo‘lish va xodimlarga hisoblash", cancel: "Bekor qilish", total: "Taqsimlandi", hint: "Asl yozuv ushbu taqsimot bilan almashtiriladi. Chop etish yoki qayta skanerlash shart emas.", workDate: "Ish sanasi", previous: "Skanerlar tanlangan sana va shu ish haqi oyiga hisoblanadi.", saved: "Donalar tanlangan xodimlarga hisoblandi." },
} as const;

export type SplitSavedRecord = {
  id: number; scan_uid: string; employee_id: number; employee_name: string; department_name: string | null;
  raw_work_json: Record<string, unknown>; quantity: string; rate_per_piece: string; total_amount: string;
  scanned_at: string; status: string;
};

export default function ScanSplit({ recordId, quantity, employee, onClose, onSaved }: {
  recordId: number; quantity: number; employee: PayrollSearchEmployee;
  onClose: () => void; onSaved: (records: SplitSavedRecord[]) => void;
}) {
  const { lang } = useT();
  const c = scanAllocationText[lang];
  const [parts, setParts] = useState(() => [
    { employee, quantity: String(Math.ceil(quantity / 2)) },
    { employee, quantity: String(Math.floor(quantity / 2)) },
  ]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const printText = { en: "Print new stickers", ru: "Печать новых наклеек", uz: "Yangi stikerlarni chop etish" }[lang];
  const total = parts.reduce((sum, part) => sum + Number(part.quantity), 0);
  const valid = total === quantity && parts.every(part => Number.isInteger(Number(part.quantity)) && Number(part.quantity) > 0);
  return <Modal open title={c.split} onClose={() => { if (!busy) onClose(); }} wide>
    <form onSubmit={async event => {
      event.preventDefault();
      if (busy || saved || !valid) return;
      setBusy(true); setError("");
      try {
        const rows = await api.post<SplitSavedRecord[]>(`/api/payroll/records/${recordId}/split`, {
          parts: parts.map(part => ({ employee_id: part.employee.employee_id, quantity: Number(part.quantity) })),
        });
        setSaved(true);
        onSaved(rows);
      } catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
      finally { setBusy(false); }
    }}>
      <p className="mb-4 text-sm">{saved ? c.saved : c.hint}</p>
      <label className="label">{c.parts}<input className="input w-28" type="number" min={2} max={Math.min(50, quantity)} value={parts.length} disabled={busy || saved} onChange={event => {
        const count = Math.min(50, quantity, Math.max(2, Number(event.target.value) || 2));
        setParts(previous => Array.from({ length: count }, (_, i) => previous[i] || { employee, quantity: "" }));
      }} /></label>
      <fieldset disabled={busy || saved} className="mt-4 space-y-4">{parts.map((part, index) => <div key={index} className="grid gap-3 border-t pt-3 sm:grid-cols-[1fr_8rem]">
        <div><div className="mb-2 text-sm">{c.employee} {index + 1}: <strong>{part.employee.employee_name}{part.employee.employee_no ? ` · ${part.employee.employee_no}` : ""}</strong></div>
          <PayrollEmployeeSearch inputId={`split-employee-${index}`} disabled={busy} onSelect={selected => setParts(previous => previous.map((row, i) => i === index ? { ...row, employee: selected } : row))} />
        </div>
        <label className="label">{c.pieces}<input className="input" type="number" min={1} max={quantity} step={1} required value={part.quantity} onChange={event => setParts(previous => previous.map((row, i) => i === index ? { ...row, quantity: event.target.value } : row))} /></label>
      </div>)}</fieldset>
      <p className="my-4" role="status">{c.total}: {total} / {quantity}</p>
      {error && <p role="alert" className="mb-3 text-red-700">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2"><button type="button" className="btn" disabled={busy} onClick={onClose}>{c.cancel}</button>{saved ? <button type="button" className="btn btn-primary" disabled={busy} onClick={async () => {
        setBusy(true); setError("");
        try { await api.openLabel(`/api/payroll/records/${recordId}/split-labels/print`); }
        catch (e: unknown) { setError(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
      }}>{printText}</button> : <button className="btn btn-primary" disabled={busy || !valid}>{c.save}</button>}</div>
    </form>
  </Modal>;
}
