"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { can, type Me } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { formatOrderReference } from "@/lib/orderRef";
import {
  CuttingDepartmentCode, cuttingFactoryMessages, cuttingFactoryNames, type CuttingFactoryOptions,
} from "@/lib/cuttingFactory";
import Modal from "./Modal";
import SearchableSelect from "./SearchableSelect";

type PlanningOrder = { id: number; order_no?: string | null; production_no: string };

export default function PlanningCuttingFactoryAction({ me, orders = [], order, onChanged }: {
  me: Me | undefined; orders?: PlanningOrder[]; order?: PlanningOrder; onChanged: () => Promise<unknown>;
}) {
  const { lang, t } = useT();
  const copy = cuttingFactoryMessages[lang];
  const [open, setOpen] = useState(false);
  const [orderId, setOrderId] = useState<number | null>(null);
  const [target, setTarget] = useState<CuttingDepartmentCode | "">("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState(false);
  const permitted = can(me, "planning.production");
  const activeOrderId = order?.id ?? orderId;
  const url = open && permitted && activeOrderId ? `/api/production-orders/${activeOrderId}/cutting-factory` : null;
  const { data, error, isLoading, isValidating, mutate } = useSWR<CuttingFactoryOptions>(url, fetcher, {
    shouldRetryOnError: false,
  });
  const current = data?.production_order_id === activeOrderId ? data : undefined;
  const choices = current?.available_departments.filter(code => code !== current.cutting_department_code) || [];

  function errorText(error: unknown) {
    const text = error instanceof Error ? error.message : "";
    const code = Object.keys(copy.reasons).find(code => text.includes(code)) as keyof typeof copy.reasons | undefined;
    return code ? copy.reasons[code] : copy.error;
  }

  async function save() {
    if (!url || !current?.can_change || !target || !choices.includes(target) || saving || isValidating || error) return;
    setSaving(true); setMessage(""); setSaved(false);
    let committed = false;
    try {
      const result = await api.patch<CuttingFactoryOptions>(url, { cutting_department_code: target });
      committed = true;
      setTarget(""); setSaved(true);
      await mutate(result, { revalidate: false });
      await Promise.all([mutate(), onChanged()]);
    } catch (error) {
      setMessage(committed ? copy.refreshError : errorText(error));
      // A refresh failure must not reject the UI handler or repeat the write.
      await mutate().catch(() => undefined);
    } finally {
      setSaving(false);
    }
  }

  if (!permitted) return null;
  return <>
    <button type="button" className="btn" onClick={() => {
      setOpen(true); setMessage(""); setSaved(false); setTarget("");
    }}>{copy.title}</button>
    <Modal open={open} onClose={() => { if (!saving) setOpen(false); }} title={copy.title}>
      <div className="space-y-4">
        {order ? <p className="text-sm">{copy.order}: <strong>{formatOrderReference(order.order_no || order.production_no)}</strong></p> : <div>
          <label className="label" htmlFor="cutting-factory-order">{copy.order}</label>
          <SearchableSelect<number> inputId="cutting-factory-order" value={orderId} disabled={saving}
            options={orders.map(order => ({ value: order.id, label: formatOrderReference(order.order_no || order.production_no) }))}
            onChange={id => { setOrderId(id); setTarget(""); setMessage(""); setSaved(false); }}
            placeholder={copy.choose} noResultsText={t("common.noData")} />
        </div>}
        {isLoading && <p role="status" className="text-sm">{t("common.loading")}</p>}
        {error && <p role="alert" className="text-sm text-red-700">{errorText(error)} <button type="button" className="underline" onClick={() => void mutate()}>{t("common.refresh")}</button></p>}
        {current && !error && <>
          <p className="text-sm">{copy.current}: <strong>{cuttingFactoryNames[current.cutting_department_code]}</strong></p>
          <p className="text-sm text-[#6f684f]">{copy.help}</p>
          {current.lock_reason && <p role="status" className="text-sm text-amber-800">{copy.reasons[current.lock_reason]}</p>}
          {current.can_change && <div>
            <label className="label" htmlFor="cutting-factory-target">{copy.destination}</label>
            <select id="cutting-factory-target" className="input" value={target} disabled={saving || isValidating}
              onChange={event => { setTarget(event.target.value as CuttingDepartmentCode | ""); setSaved(false); }}>
              <option value="">{copy.selectFactory}</option>
              {choices.map(code => <option key={code} value={code}>{cuttingFactoryNames[code]}</option>)}
            </select>
          </div>}
        </>}
        {message && <p role="alert" className="text-sm text-red-700">{message}</p>}
        {saved && <p role="status" className="text-sm text-emerald-700">{copy.saved}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" disabled={saving} onClick={() => setOpen(false)}>{t("common.close")}</button>
          <button type="button" className="btn btn-primary" disabled={saving || isValidating || Boolean(error) || !current?.can_change || !target || !choices.includes(target)} onClick={save}>
            {saving ? t("common.saving") : t("common.save")}
          </button>
        </div>
      </div>
    </Modal>
  </>;
}
