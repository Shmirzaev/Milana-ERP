"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function ScanBundlePage() {
  const { t } = useT();
  const [code, setCode] = useState("");
  const [bundle, setBundle] = useState<any>(null);
  const [msg, setMsg] = useState("");

  async function lookup() {
    setMsg("");
    try {
      const b = await api.get(`/api/bundles/barcode/${encodeURIComponent(code.trim())}`);
      setBundle(b);
    } catch (e: any) {
      setBundle(null);
      setMsg(e.message);
    }
  }

  async function act(action: "send-printing" | "receive-printing" | "send-sewing" | "receive-sewing") {
    if (!bundle) return;
    try {
      const b = await api.post(`/api/bundles/${bundle.id}/${action}`);
      setBundle(b);
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.bundleScan.title")} subtitle={t("page.bundleScan.subtitle")} />
      <div className="card max-w-2xl p-6">
        <div className="mb-4 flex gap-2">
          <input
            className="input"
            autoFocus
            placeholder={t("ph.bundleBarcode")}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") lookup(); }}
          />
          <button className="btn btn-primary" onClick={lookup}>{t("btn.lookup")}</button>
        </div>
        {msg && <div className="mb-3 text-sm">{msg}</div>}
        {bundle && (
          <div>
            <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
              <div className="text-slate-500">{t("field.bundleNo")}</div><div>{bundle.bundle_no}</div>
              <div className="text-slate-500">{t("field.model")}</div><div>{bundle.model_id}</div>
              <div className="text-slate-500">{t("field.color")} / {t("field.size")}</div><div>{bundle.color} / {bundle.size}</div>
              <div className="text-slate-500">{t("field.quantity")}</div><div>{bundle.quantity}</div>
              <div className="text-slate-500">{t("common.status")}</div><div><span className="badge">{bundle.status}</span></div>
              <div className="text-slate-500">{t("field.currentDept")}</div><div>{bundle.current_department_id}</div>
              <div className="text-slate-500">{t("field.nextDept")}</div><div>{bundle.next_department_id}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button className="btn" onClick={() => act("send-printing")}>{t("btn.sendToPrinting")}</button>
              <button className="btn" onClick={() => act("receive-printing")}>{t("btn.receiveAtPrinting")}</button>
              <button className="btn" onClick={() => act("send-sewing")}>{t("btn.sendToSewing")}</button>
              <button className="btn btn-primary" onClick={() => act("receive-sewing")}>{t("btn.receiveAtSewing")}</button>
            </div>
            <div className="mt-4">
              <button type="button" className="text-brand-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${bundle.id}/label`)}>{t("btn.printLabel")}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
