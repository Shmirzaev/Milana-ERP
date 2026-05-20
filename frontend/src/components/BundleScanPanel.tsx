"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";

type BundleAction = "send-printing" | "receive-printing" | "send-sewing" | "receive-sewing";
type Scope = "all" | "cutting" | "printing" | "sewing";

export default function BundleScanPanel({ scope = "all" }: { scope?: Scope }) {
  const { t } = useT();
  const { me } = useMe();
  const [code, setCode] = useState("");
  const [bundle, setBundle] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const canCuttingScan = can(me, "*", "cutting.bundles");
  const canPrintingScan = can(me, "*", "printing.bundles");
  const canSewingScan = can(me, "*", "sewing.bundles");

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

  async function act(action: BundleAction) {
    if (!bundle) return;
    try {
      const b = await api.post(`/api/bundles/${bundle.id}/${action}`);
      setBundle(b);
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  const includeCutting = scope === "all" || scope === "cutting";
  const includePrinting = scope === "all" || scope === "printing";
  const includeSewing = scope === "all" || scope === "sewing";

  const availableActions: Array<{ key: BundleAction; label: string; primary?: boolean }> = [];
  if (bundle?.status === "created" && canCuttingScan && includeCutting) {
    availableActions.push({ key: "send-printing", label: t("btn.sendToPrinting") });
    availableActions.push({ key: "send-sewing", label: t("btn.sendToSewing"), primary: true });
  }
  if (bundle?.status === "sent_to_printing" && canPrintingScan && includePrinting) {
    availableActions.push({ key: "receive-printing", label: t("btn.receiveAtPrinting"), primary: true });
  }
  if (bundle?.status === "received_printing" && canPrintingScan && includePrinting) {
    availableActions.push({ key: "send-sewing", label: t("btn.sendToSewing"), primary: true });
  }
  if (bundle?.status === "sent_to_sewing" && canSewingScan && includeSewing) {
    availableActions.push({ key: "receive-sewing", label: t("btn.receiveAtSewing"), primary: true });
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
            onKeyDown={(e) => {
              if (e.key === "Enter") lookup();
            }}
          />
          <button className="btn btn-primary" onClick={lookup}>
            {t("btn.lookup")}
          </button>
        </div>
        {msg && <div className="mb-3 text-sm">{msg}</div>}
        {bundle && (
          <div>
            <div className="mb-4 grid grid-cols-2 gap-2 text-sm">
              <div className="text-slate-500">{t("field.bundleNo")}</div>
              <div>{bundle.bundle_no}</div>
              <div className="text-slate-500">{t("field.model")}</div>
              <div>{bundle.model_id}</div>
              <div className="text-slate-500">
                {t("field.color")} / {t("field.size")}
              </div>
              <div>
                {bundle.color} / {bundle.size}
              </div>
              <div className="text-slate-500">{t("field.quantity")}</div>
              <div>{bundle.quantity}</div>
              <div className="text-slate-500">{t("common.status")}</div>
              <div>
                <span className="badge">{statusLabel(bundle.status, t)}</span>
              </div>
              <div className="text-slate-500">{t("field.currentDept")}</div>
              <div>{bundle.current_department_id}</div>
              <div className="text-slate-500">{t("field.nextDept")}</div>
              <div>{bundle.next_department_id}</div>
            </div>
            <div className="flex flex-wrap gap-2">
              {availableActions.map((a) => (
                <button key={a.key} className={`btn ${a.primary ? "btn-primary" : ""}`} onClick={() => act(a.key)}>
                  {a.label}
                </button>
              ))}
              {availableActions.length === 0 && <div className="text-sm text-slate-500">{t("page.bundleScan.noActions")}</div>}
            </div>
            <div className="mt-4">
              <button type="button" className="text-brand-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${bundle.id}/label`)}>
                {t("btn.printLabel")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
