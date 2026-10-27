"use client";

import { useState } from "react";
import useSWR from "swr";
import Modal from "@/components/Modal";
import PayrollEmployeeSearch from "@/components/PayrollEmployeeSearch";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useMe } from "@/lib/auth";
import { removePayrollScanHistoryForLabel } from "@/lib/payrollScanStorage";

export const splitCorrectionText = {
  en: { edit: "Edit split allocation", hint: "Correct the saved employees, pieces, operation names and rates. Total pieces must stay the same. Saving recalculates credited payroll; closed or paid work cannot be changed.", pieces: "Pieces", operation: "Operation name", rate: "Rate per piece", total: "Allocated pieces", reason: "Reason for correction", save: "Save payroll correction", saved: "Correction saved. Reprint the updated stickers.", print: "Print updated stickers", cancel: "Close", reload: "Reload allocations", loading: "Loading allocations…", employee: "Employee" },
  ru: { edit: "Изменить распределение", hint: "Исправьте сотрудников, количество, названия операций и расценки. Общее количество должно остаться прежним. Сохранение пересчитает начисления; закрытую или оплаченную работу изменить нельзя.", pieces: "Штук", operation: "Название операции", rate: "Расценка за штуку", total: "Распределено штук", reason: "Причина исправления", save: "Сохранить исправление начислений", saved: "Исправление сохранено. Напечатайте обновлённые наклейки.", print: "Печать обновлённых наклеек", cancel: "Закрыть", reload: "Обновить распределение", loading: "Загрузка распределения…", employee: "Сотрудник" },
  uz: { edit: "Taqsimotni tahrirlash", hint: "Saqlangan xodimlar, donalar, operatsiya nomlari va narxlarni tuzating. Jami dona o‘zgarmasligi kerak. Saqlash hisoblangan ish haqini qayta hisoblaydi; yopilgan yoki to‘langan ishni o‘zgartirib bo‘lmaydi.", pieces: "Dona", operation: "Operatsiya nomi", rate: "Dona uchun narx", total: "Taqsimlangan dona", reason: "Tuzatish sababi", save: "Ish haqi tuzatishini saqlash", saved: "Tuzatish saqlandi. Yangilangan stikerlarni chop eting.", print: "Yangilangan stikerlarni chop etish", cancel: "Yopish", reload: "Taqsimotni yangilash", loading: "Taqsimot yuklanmoqda…", employee: "Xodim" },
};

type Part = {
  label_id: number; label_uid: string; employee_id: number; employee_name: string; quantity: number;
  operation_name: string; rate_per_piece: string; total_amount: string; currency: string;
};
type Allocation = { revision: string; original_record_id: number; total_quantity: number; parts: Part[] };

export default function SplitAllocationEditor({ labelId, onClose, onSaved }: {
  labelId: number; onClose: () => void; onSaved: () => void;
}) {
  const { lang } = useT();
  const c = splitCorrectionText[lang];
  const endpoint = `/api/payroll/qr-labels/${labelId}/split-allocation`;
  const { data, error, mutate, isValidating } = useSWR<Allocation>(endpoint, fetcher, { revalidateOnFocus: false });
  const [busy, setBusy] = useState(false);
  const close = () => { if (!busy) onClose(); };
  return <Modal open wide title={c.edit} onClose={close} closeOnOutsideClick={false}>
    {!data && !error && <p role="status">{c.loading}</p>}
    {error && <p role="alert" className="mb-3 text-red-700">{error.message}</p>}
    {data && <AllocationForm key={data.revision} initial={data} endpoint={endpoint} setBusy={setBusy} onSaved={onSaved} onClose={close} onReload={() => { void mutate(); }} />}
    {error && <button type="button" className="btn" disabled={isValidating} onClick={() => void mutate()}>{c.reload}</button>}
  </Modal>;
}

function AllocationForm({ initial, endpoint, setBusy, onSaved, onClose, onReload }: {
  initial: Allocation; endpoint: string; setBusy: (value: boolean) => void;
  onSaved: () => void; onClose: () => void; onReload: () => void;
}) {
  const { lang } = useT();
  const { me } = useMe();
  const c = splitCorrectionText[lang];
  const [view, setView] = useState(initial);
  const [parts, setParts] = useState(initial.parts);
  const [reason, setReason] = useState("");
  const [busy, setLocalBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const total = parts.reduce((sum, part) => sum + Number(part.quantity), 0);
  const valid = total === view.total_quantity && reason.trim().length >= 3 && parts.every(part =>
    Number.isInteger(Number(part.quantity)) && Number(part.quantity) > 0 && part.operation_name.trim()
    && Number.isFinite(Number(part.rate_per_piece)) && Number(part.rate_per_piece) >= 0,
  );
  function update(index: number, patch: Partial<Part>) {
    setParts(current => current.map((part, i) => i === index ? { ...part, ...patch } : part));
    setDirty(true); setSaved(false);
  }
  function working(value: boolean) { setLocalBusy(value); setBusy(value); }
  return <form onSubmit={async event => {
    event.preventDefault();
    if (busy || !valid) return;
    working(true); setError("");
    try {
      const result = await api.patch<Allocation>(endpoint, {
        revision: view.revision, reason: reason.trim(), parts: parts.map(part => ({
          label_id: part.label_id, employee_id: part.employee_id, quantity: Number(part.quantity),
          operation_name: part.operation_name.trim(), rate_per_piece: part.rate_per_piece,
        })),
      });
      setView(result); setParts(result.parts); setDirty(false); setSaved(true);
      try {
        for (const part of result.parts) removePayrollScanHistoryForLabel(part.label_uid, window.localStorage, me?.factory_code);
      } catch { /* Payroll is saved; blocked browser storage cannot undo it. Reopening reads the server. */ }
      onSaved();
    } catch (err: unknown) { setError(err instanceof Error ? err.message : String(err)); }
    finally { working(false); }
  }}>
    <p className="mb-4 text-sm">{c.hint}</p>
    <fieldset disabled={busy} className="space-y-4">
      {parts.map((part, index) => <div key={part.label_id} className="border-t pt-3">
        <p className="text-sm"><b>{c.employee} {index + 1}: {part.employee_name}</b></p>
        <PayrollEmployeeSearch inputId={`correct-split-${part.label_id}`} disabled={busy} onSelect={employee => update(index, { employee_id: employee.employee_id, employee_name: employee.employee_name })} />
        <div className="mt-3 grid gap-3 sm:grid-cols-[5rem_1fr_8rem]">
          <label className="label">{c.pieces}<input className="input" type="number" min={1} max={view.total_quantity} step={1} required value={part.quantity || ""} onChange={event => update(index, { quantity: Number(event.target.value) })} /></label>
          <label className="label">{c.operation}<input className="input" required maxLength={255} value={part.operation_name} onChange={event => update(index, { operation_name: event.target.value })} /></label>
          <label className="label">{c.rate} ({part.currency})<input className="input" required type="number" min={0} max="9999999999.9999" step="0.0001" value={part.rate_per_piece} onChange={event => update(index, { rate_per_piece: event.target.value })} /></label>
        </div>
      </div>)}
      <p role="status" className="text-sm">{c.total}: <b>{total} / {view.total_quantity}</b></p>
      <label className="label">{c.reason}<input className="input" required minLength={3} maxLength={255} value={reason} onChange={event => setReason(event.target.value)} /></label>
    </fieldset>
    {error && <div className="my-3"><p role="alert" className="mb-2 text-red-700">{error}</p><button type="button" className="btn" disabled={busy} onClick={onReload}>{c.reload}</button></div>}
    {saved && <p role="status" className="my-3 text-sm">{c.saved}</p>}
    <div className="mt-4 flex flex-wrap justify-end gap-2">
      <button type="button" className="btn" disabled={busy} onClick={onClose}>{c.cancel}</button>
      <button type="button" className="btn" disabled={busy || dirty} onClick={async () => {
        working(true); setError("");
        try { await api.openLabel(`/api/payroll/records/${view.original_record_id}/split-labels/print`); }
        catch (err: unknown) { setError(err instanceof Error ? err.message : String(err)); }
        finally { working(false); }
      }}>{c.print}</button>
      <button type="submit" className="btn btn-primary" disabled={busy || !valid || !dirty}>{c.save}</button>
    </div>
  </form>;
}
