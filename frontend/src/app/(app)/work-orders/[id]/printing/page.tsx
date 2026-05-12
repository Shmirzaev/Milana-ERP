"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function PrintingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [f, setF] = useState({ input_qty: 0, printed_qty: 0, passed_qty: 0, rejected_qty: 0, defect_reason: "", print_type: "", notes: "" });
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/printing/records", { work_order_id: id, ...f });
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.printing.title", { id })} />
      <form onSubmit={submit} className="card max-w-2xl space-y-3 p-6">
        <div>
          <label className="label">{t("field.inputQty")}</label>
          <input className="input" type="number" value={f.input_qty} onChange={(e) => setF({ ...f, input_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.output")}</label>
          <input className="input" type="number" value={f.printed_qty} onChange={(e) => setF({ ...f, printed_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.passed")}</label>
          <input className="input" type="number" value={f.passed_qty} onChange={(e) => setF({ ...f, passed_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.rejected")}</label>
          <input className="input" type="number" value={f.rejected_qty} onChange={(e) => setF({ ...f, rejected_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.printType")}</label>
          <input className="input" value={f.print_type} onChange={(e) => setF({ ...f, print_type: e.target.value })} />
        </div>
        <div>
          <label className="label">{t("field.defectReason")}</label>
          <input className="input" value={f.defect_reason} onChange={(e) => setF({ ...f, defect_reason: e.target.value })} />
        </div>
        <div>
          <label className="label">{t("common.notes")}</label>
          <textarea className="input" rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
        </div>
        <button className="btn btn-primary">{t("btn.saveRecord")}</button>
        {msg && <div className="mt-2 text-sm">{msg}</div>}
      </form>
    </div>
  );
}
