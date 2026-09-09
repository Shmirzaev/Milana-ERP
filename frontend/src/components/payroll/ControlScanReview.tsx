"use client";

import { useT } from "@/lib/i18n";
import { formatOrderReference } from "@/lib/orderRef";

export type ControlPreview = {
  review_token: string;
  work: {
    label_id?: string | null;
    model_code?: string | null;
    sales_order_no?: string | null;
    production_no?: string | null;
    size?: string | null;
    quantity?: number | string | null;
    rate_per_piece?: number | string | null;
    currency?: string | null;
  };
  operations: {
    label_uid: string;
    qr_token: string;
    operation_code?: string | null;
    operation_name?: string | null;
    status: string;
    payroll_status?: string | null;
    employee_name?: string | null;
  }[];
};

export const controlScanMessages = {
  en: { title: "Confirm Control operation", hint: "Review operations for this model, order and size. Only this Control operation will be credited after confirmation.", confirm: "Confirm and record Control", cancel: "Cancel", pending: "Confirm or cancel the Control review before scanning again.", saving: "Confirming…", operation: "Paid operation", status: "Scan status", scanned: "Scanned", cancelled: "Cancelled", available: "Not scanned", employee: "Employee", amount: "Control amount", error: "Control confirmation failed. Retry to check the same QR safely." },
  ru: { title: "Подтвердить операцию контроля", hint: "Проверьте операции этой модели, заказа и размера. Только операция контроля будет начислена после подтверждения.", confirm: "Подтвердить и начислить контроль", cancel: "Отмена", pending: "Подтвердите или отмените контроль перед следующим сканированием.", saving: "Подтверждение…", operation: "Оплачиваемая операция", status: "Статус сканирования", scanned: "Отсканировано", cancelled: "Отменено", available: "Не отсканировано", employee: "Сотрудник", amount: "Сумма контроля", error: "Не удалось подтвердить контроль. Повторите попытку для того же QR." },
  uz: { title: "Kontrol amalini tasdiqlash", hint: "Ushbu model, buyurtma va o‘lcham amallarini tekshiring. Faqat Kontrol amali tasdiqlangandan keyin hisoblanadi.", confirm: "Tasdiqlash va Kontrolni hisoblash", cancel: "Bekor qilish", pending: "Qayta skan qilishdan oldin Kontrolni tasdiqlang yoki bekor qiling.", saving: "Tasdiqlanmoqda…", operation: "Haq to‘lanadigan amal", status: "Skan holati", scanned: "Skan qilingan", cancelled: "Bekor qilingan", available: "Skan qilinmagan", employee: "Xodim", amount: "Kontrol summasi", error: "Kontrol tasdiqlanmadi. Shu QR uchun qayta urinib ko‘ring." },
};

export function isControlWork(work: { operation_section?: string | null; operation_name?: string | null; operation_code?: string | null; requires_control_confirmation?: boolean }) {
  return work.requires_control_confirmation || [work.operation_section, work.operation_name, work.operation_code].some(
    (value) => (value?.toLowerCase().match(/[\p{L}]+/gu) || []).some((word) => ["control", "kontrol", "контроль", "nazorat", "qc"].includes(word)),
  );
}

export default function ControlScanReview({ preview, employeeName, busy, error, onConfirm, onCancel }: {
  preview: ControlPreview;
  employeeName: string;
  busy: boolean;
  error: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { lang } = useT();
  const text = controlScanMessages[lang];
  return (
    <section className="card mb-4 p-4" aria-labelledby="control-review-title" data-testid="control-review">
      <h2 id="control-review-title" className="app-card-title">{text.title}</h2>
      <p className="mt-2 text-sm">{text.hint}</p>
      <p className="my-3 text-sm">{employeeName} · {formatOrderReference(preview.work.sales_order_no || preview.work.production_no, "—")} · {preview.work.model_code || "—"} · {preview.work.size || "—"}</p>
      <div className="overflow-x-auto">
        <table className="table min-w-[580px] w-full">
          <thead><tr><th>QR</th><th>{text.operation}</th><th>{text.status}</th><th>{text.employee}</th></tr></thead>
          <tbody>{preview.operations.map((row) => (
            <tr key={row.label_uid}>
              <td>{row.qr_token}</td>
              <td>{row.operation_code ? `${row.operation_code} · ` : ""}{row.operation_name || "—"}</td>
              <td className={row.status === "scanned" && row.payroll_status !== "voided" ? "text-emerald-700" : "text-amber-800"}>{row.payroll_status === "voided" ? text.cancelled : row.status === "scanned" ? text.scanned : text.available}</td>
              <td>{row.employee_name || "—"}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <p className="my-3 font-semibold">{text.amount}: {(Number(preview.work.quantity || 0) * Number(preview.work.rate_per_piece || 0)).toLocaleString(lang)} {preview.work.currency || "UZS"}</p>
      {error ? <p className="mb-3 text-sm text-red-700" role="alert">{error}</p> : null}
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-primary" onClick={onConfirm} disabled={busy}>{busy ? text.saving : text.confirm}</button>
        <button type="button" className="btn" onClick={onCancel} disabled={busy}>{text.cancel}</button>
      </div>
    </section>
  );
}
