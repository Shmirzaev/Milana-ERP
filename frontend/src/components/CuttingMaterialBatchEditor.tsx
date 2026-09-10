"use client";

import { useState } from "react";
import useSWR from "swr";
import SearchableSelect from "@/components/SearchableSelect";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

export type CuttingBatchOption = {
  id: number;
  item_name?: string | null;
  item_sku?: string | null;
  item_id: number;
  batch_no?: string | null;
  internal_batch_no?: string | null;
  available_quantity?: number | null;
  quantity?: number | null;
  unit?: string | null;
  warehouse_name?: string | null;
};

export default function CuttingMaterialBatchEditor({ workOrderId, batchId, assignedIds, unit, disabled, onEditing, onChanged }: {
  workOrderId: number;
  batchId: number;
  assignedIds: number[];
  unit: string;
  disabled: boolean;
  onEditing: (editing: boolean) => void;
  onChanged: (batch: CuttingBatchOption) => Promise<void>;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<CuttingBatchOption | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { data: batches = [], error: loadError, isLoading } = useSWR<CuttingBatchOption[]>(
    open ? `/api/inventory/batches?group=materials&hide_empty=true&page_size=100&q=${encodeURIComponent(search)}` : null, fetcher,
  );
  function close() {
    setOpen(false);
    onEditing(false);
    setSelected(null);
    setError("");
  }
  async function save() {
    if (!selected || saving) return;
    setSaving(true);
    setError("");
    try {
      await api.patch(`/api/work-orders/${workOrderId}/cutting-materials/${batchId}`, {
        stock_batch_id: selected.id,
      });
      await onChanged(selected);
      close();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setSaving(false);
    }
  }
  if (!open) return <button type="button" className="btn mt-2" disabled={disabled} onClick={() => { setOpen(true); onEditing(true); }}>{t("cuttingBatch.change")}</button>;
  const options = [...(selected ? [selected] : []), ...batches.filter((batch) => batch.id !== selected?.id)]
    .filter((batch) => !assignedIds.includes(batch.id) && batch.unit === unit)
    .map((batch) => ({ value: batch.id, label: `${batch.item_name || batch.item_sku || ""} · ${batch.batch_no || batch.internal_batch_no || ""}`, metaText: `${batch.available_quantity ?? batch.quantity ?? 0} ${batch.unit} · ${batch.warehouse_name || ""}` }));
  return <div className="mt-3 space-y-2">
    <label className="block text-sm">{t("cuttingBatch.select")}</label>
    <SearchableSelect<number> value={selected?.id} options={options} disabled={saving}
      onChange={(value) => setSelected(batches.find((batch) => batch.id === value) || selected)}
      placeholder={t("passportMaterial.search")} noResultsText={t("passportMaterial.noResults")}
      serverFilter onSearchChange={setSearch} loading={isLoading} />
    <p className="text-xs text-[#6f684f]">{t("cuttingBatch.help")}</p>
    {(error || loadError) && <p role="alert" className="text-sm text-red-600">{error || t("passportMaterial.loadError")}</p>}
    <div className="flex gap-2">
      <button type="button" className="btn" disabled={saving || !selected} onClick={save}>{t(saving ? "common.saving" : "btn.save")}</button>
      <button type="button" className="btn" disabled={saving} onClick={close}>{t("common.cancel")}</button>
    </div>
  </div>;
}
