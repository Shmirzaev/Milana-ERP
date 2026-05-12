"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function SewingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const [f, setF] = useState({
    input_qty: 0,
    sewn_qty: 0,
    passed_qty: 0,
    failed_qty: 0,
    rework_qty: 0,
    rejected_qty: 0,
    line_name: "",
    defect_reason: "",
    notes: "",
  });
  const [msg, setMsg] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/sewing/records", { work_order_id: id, ...f });
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.sewing.title", { id })} subtitle={t("page.sewing.subtitle")} />
      <form onSubmit={submit} className="card max-w-2xl space-y-3 p-6">
        <div>
          <label className="label">{t("field.inputQty")}</label>
          <input className="input" type="number" value={f.input_qty} onChange={(e) => setF({ ...f, input_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.output")}</label>
          <input className="input" type="number" value={f.sewn_qty} onChange={(e) => setF({ ...f, sewn_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.passed")}</label>
          <input className="input" type="number" value={f.passed_qty} onChange={(e) => setF({ ...f, passed_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.failed")}</label>
          <input className="input" type="number" value={f.failed_qty} onChange={(e) => setF({ ...f, failed_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.rework")}</label>
          <input className="input" type="number" value={f.rework_qty} onChange={(e) => setF({ ...f, rework_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.rejected")}</label>
          <input className="input" type="number" value={f.rejected_qty} onChange={(e) => setF({ ...f, rejected_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.lineName")}</label>
          <input className="input" value={f.line_name} onChange={(e) => setF({ ...f, line_name: e.target.value })} />
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
