"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import Modal from "@/components/Modal";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errorMessages";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

const translations = {
  en: {
    action: "Return to preparation", reason: "Reason", cancel: "Cancel", busy: "Returning…",
    explanation: "This reverses the shipment and its unpaid invoice, restores the packages to warehouse stock, and opens it in Shipments. Scan the packages again before dispatch. Enter any agreed invoice total again after reviewing the contents.",
    confirm: "All packages in this shipment are back in the warehouse.",
    stale: "This shipment has changed. Refresh the page before returning it.",
    stock: "Package stock or reservations have changed. Reconcile the stock before returning this shipment.",
    finance: "Finance reconciliation is required: an invoice has payments or an external posting, or the order is shared with another shipment.",
    confirmation: "Confirm that all packages are back in the warehouse and enter a reason.",
  },
  ru: {
    action: "Вернуть в подготовку", reason: "Причина", cancel: "Отмена", busy: "Возврат…",
    explanation: "Отгрузка и её неоплаченный счёт будут отменены, упаковки вернутся на склад, а отгрузка откроется в разделе «Отгрузки». Перед отправкой отсканируйте упаковки заново. После проверки состава повторно укажите согласованную сумму счёта.",
    confirm: "Все упаковки этой отгрузки снова находятся на складе.",
    stale: "Отгрузка изменилась. Обновите страницу перед возвратом.",
    stock: "Остатки или резервы упаковок изменились. Сначала выполните сверку склада.",
    finance: "Нужна сверка финансов: по счёту есть оплаты или внешняя проводка, либо заказ связан с другой отгрузкой.",
    confirmation: "Подтвердите возврат всех упаковок на склад и укажите причину.",
  },
  uz: {
    action: "Tayyorlashga qaytarish", reason: "Sabab", cancel: "Bekor qilish", busy: "Qaytarilmoqda…",
    explanation: "Jo‘natma va uning to‘lanmagan hisobi bekor qilinadi, qadoqlar ombor qoldig‘iga qaytariladi va jo‘natma «Jo‘natmalar» bo‘limida ochiladi. Jo‘natishdan oldin qadoqlarni qayta skanerlang. Tarkibni tekshirgach, kelishilgan hisob summasini qayta kiriting.",
    confirm: "Ushbu jo‘natmadagi barcha qadoqlar omborga qaytgan.",
    stale: "Jo‘natma o‘zgargan. Qaytarishdan oldin sahifani yangilang.",
    stock: "Qadoq qoldiqlari yoki rezervlari o‘zgargan. Avval ombor hisobini tekshiring.",
    finance: "Moliyaviy tekshiruv kerak: hisob bo‘yicha to‘lov yoki tashqi o‘tkazma mavjud yoxud buyurtma boshqa jo‘natmaga bog‘langan.",
    confirmation: "Barcha qadoqlar omborga qaytganini tasdiqlang va sababini kiriting.",
  },
};

export default function ShipmentReopenAction({ shipment }: {
  shipment: { id: number; shipment_no?: string | null; status: string; shipped_at?: string | null };
}) {
  const { lang } = useT();
  const text = translations[lang];
  const { me } = useMe();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!can(me, "storage.shipment") || !["shipped", "delivered"].includes(shipment.status)) return null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !confirmed || reason.trim().length < 3) return;
    setBusy(true); setError("");
    try {
      await api.post(`/api/shipments/${shipment.id}/reopen`, {
        reason: reason.trim(), packages_returned: confirmed, expected_shipped_at: shipment.shipped_at || null,
      });
      // Invalidate both history and preparation caches before navigating to the reopened row.
      void mutate(key => typeof key === "string" && (key.startsWith("/api/shipments") || key.startsWith("/api/sales-orders")));
      setOpen(false);
      router.push(`/shipments?shipment_id=${shipment.id}`);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : String(caught);
      const detail = caught instanceof ApiError ? caught.rawDetail : message;
      const code = detail.match(/shipment_reopen_(stale|stock|finance|confirmation)/)?.[1] as "stale" | "stock" | "finance" | "confirmation" | undefined;
      setError(code ? text[code] : message);
    } finally { setBusy(false); }
  }

  return <>
    <button type="button" className="btn" onClick={() => { setError(""); setOpen(true); }}>{text.action}</button>
    <Modal open={open} onClose={() => { if (!busy) setOpen(false); }} title={`${text.action} · ${shipment.shipment_no || ""}`}>
      <form onSubmit={submit} className="space-y-4 whitespace-normal text-sm">
        <p className="text-[var(--erp-text-muted)]">{text.explanation}</p>
        <label className="block">{text.reason}
          <textarea className="input mt-1 block w-full" rows={3} required minLength={3} maxLength={1000}
            value={reason} onChange={event => setReason(event.target.value)} disabled={busy} />
        </label>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} disabled={busy} />
          <span>{text.confirm}</span>
        </label>
        {error && <p role="alert" className="text-red-700">{error}</p>}
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-primary" disabled={busy || !confirmed || reason.trim().length < 3}>{busy ? text.busy : text.action}</button>
          <button type="button" className="btn" disabled={busy} onClick={() => setOpen(false)}>{text.cancel}</button>
        </div>
      </form>
    </Modal>
  </>;
}
