"use client";
import { useState } from "react";
import Modal from "@/components/Modal";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const copy = {
  en: { add: "Add client", name: "Client name", phone: "Phone", save: "Save client", cancel: "Cancel" },
  ru: { add: "Добавить клиента", name: "Имя клиента", phone: "Телефон", save: "Сохранить клиента", cancel: "Отмена" },
  uz: { add: "Mijoz qo‘shish", name: "Mijoz nomi", phone: "Telefon", save: "Mijozni saqlash", cancel: "Bekor qilish" },
};
export default function ShipmentAddClient({ disabled, onCreated }: { disabled: boolean; onCreated: (client: { id: number; name: string }) => void }) {
  const { lang } = useT();
  const text = copy[lang];
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return <>
    <button type="button" className="btn" disabled={disabled} onClick={() => { setError(""); setOpen(true); }}>{text.add}</button>
    <Modal open={open} onClose={() => { if (!busy) setOpen(false); }} title={text.add}>
      <form className="space-y-4" onSubmit={async event => {
        event.preventDefault();
        if (busy || !name.trim()) return;
        setBusy(true); setError("");
        try {
          const client = await api.post<{ id: number; name: string }>("/api/shipments/customers", { name: name.trim(), phone: phone.trim() || null });
          onCreated(client); setName(""); setPhone(""); setOpen(false);
        } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
      }}>
        <label className="block text-sm">{text.name}<input className="input mt-1 w-full" required maxLength={255} value={name} disabled={busy} onChange={e => setName(e.target.value)} /></label>
        <label className="block text-sm">{text.phone}<input className="input mt-1 w-full" type="tel" maxLength={64} value={phone} disabled={busy} onChange={e => setPhone(e.target.value)} /></label>
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-2"><button type="button" className="btn" disabled={busy} onClick={() => setOpen(false)}>{text.cancel}</button><button className="btn btn-primary" disabled={busy || !name.trim()}>{text.save}</button></div>
      </form>
    </Modal>
  </>;
}
