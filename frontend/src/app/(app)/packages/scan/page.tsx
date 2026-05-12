"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function ScanPackagePage() {
  const { t } = useT();
  const [code, setCode] = useState("");
  const [pkg, setPkg] = useState<any>(null);
  const [msg, setMsg] = useState("");

  async function lookup() {
    setMsg("");
    try {
      const p = await api.get(`/api/packages/barcode/${encodeURIComponent(code.trim())}`);
      setPkg(p);
    } catch (e: any) {
      setPkg(null);
      setMsg(e.message);
    }
  }

  async function act(action: "receive-storage" | "reserve" | "ship" | "mark-delivered" | "mark-damaged") {
    if (!pkg) return;
    try {
      const p = await api.post(`/api/packages/${pkg.id}/${action}`);
      setPkg(p);
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.packageScan.title")} subtitle={t("page.packageScan.subtitle")} />
      <div className="card max-w-2xl p-6">
        <div className="mb-4 flex gap-2">
          <input
            className="input"
            autoFocus
            placeholder={t("ph.packageBarcode")}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") lookup(); }}
          />
          <button className="btn btn-primary" onClick={lookup}>{t("btn.lookup")}</button>
        </div>
        {msg && <div className="mb-3 text-sm">{msg}</div>}
        {pkg && (
          <div>
            <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
              <div className="text-slate-500">{t("field.packageNo")}</div><div>{pkg.package_no}</div>
              <div className="text-slate-500">{t("field.model")}</div><div>{pkg.model_id}</div>
              <div className="text-slate-500">{t("field.color")}</div><div>{pkg.color}</div>
              <div className="text-slate-500">{t("field.totalQty")}</div><div>{pkg.total_quantity}</div>
              <div className="text-slate-500">{t("common.status")}</div><div><span className="badge">{pkg.status}</span></div>
            </div>
            {pkg.items && (
              <div className="mb-3">
                <h4 className="text-sm font-medium">{t("page.packageScan.sizesInside")}</h4>
                <ul className="text-sm">{pkg.items.map((i: any) => <li key={i.id}>{i.size}: {i.quantity}</li>)}</ul>
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary" onClick={() => act("receive-storage")}>{t("btn.receiveAtStorage")}</button>
              <button className="btn" onClick={() => act("reserve")}>{t("btn.reserve")}</button>
              <button className="btn" onClick={() => act("ship")}>{t("btn.ship")}</button>
              <button className="btn" onClick={() => act("mark-delivered")}>{t("btn.markDelivered")}</button>
              <button className="btn btn-danger" onClick={() => act("mark-damaged")}>{t("btn.markDamaged")}</button>
            </div>
            <div className="mt-4">
              <button type="button" className="text-brand-600 hover:underline" onClick={() => api.openLabel(`/api/packages/${pkg.id}/label`)}>{t("btn.printLabel")}</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
