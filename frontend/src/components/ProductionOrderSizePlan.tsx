"use client";
import { useId, useRef, useState } from "react";
import { GARMENT_SIZE_OPTIONS } from "@/lib/garmentSizes";
import { useT } from "@/lib/i18n";

type PlanRow = {
  id: number;
  color: string;
  size: string;
  planned_quantity: number;
  completed_quantity: number;
};
export type ProductionSizeEdit = { id: number; original_size: string; size: string };

export default function ProductionOrderSizePlan({ items, canEdit, onSave }: {
  items: PlanRow[];
  canEdit: boolean;
  onSave: (items: ProductionSizeEdit[]) => Promise<void>;
}) {
  const { t } = useT();
  const listId = useId();
  const savingRef = useRef(false);
  const [draft, setDraft] = useState<(PlanRow & { original_size: string })[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  function startEdit() {
    setDraft(items.map((row) => ({ ...row, original_size: row.size })));
    setError("");
    setSaved(false);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || savingRef.current || !canEdit) return;
    if (draft.some((row) => !row.size.trim())) {
      setError(t("productionSizes.required"));
      return;
    }
    const identities = draft.map((row) => JSON.stringify([row.color.trim().toLowerCase(), row.size.trim().toLowerCase()]));
    if (new Set(identities).size !== identities.length) {
      setError(t("productionSizes.duplicate"));
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setError("");
    try {
      await onSave(draft.map((row) => ({ id: row.id, original_size: row.original_size, size: row.size.trim() })));
      setDraft(null);
      setSaved(true);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "";
      const code = ["locked", "stale", "required", "duplicate"].find((code) => message.includes(`production_sizes_${code}`));
      setError(t(code ? `productionSizes.${code}` : "productionSizes.failed"));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-medium">{t("page.poDetail.plan")}</h3>
        {canEdit && items.length > 0 && !draft && (
          <button type="button" className="btn" onClick={startEdit} aria-label={t("productionSizes.edit")}>
            {t("btn.edit")}
          </button>
        )}
      </div>
      <form onSubmit={save}>
        <div className="overflow-x-auto">
          <table className="table">
            <thead><tr>
              <th>{t("field.color")}</th><th>{t("field.size")}</th>
              <th>{t("page.poDetail.planned")}</th><th>{t("page.poDetail.completed")}</th>
            </tr></thead>
            <tbody>{(draft || items).map((row, index) => (
              <tr key={row.id}>
                <td>{row.color}</td>
                <td>{draft ? (
                  <input
                    className="input min-w-24 max-w-36"
                    aria-label={t("productionSizes.rowLabel", { row: index + 1, color: row.color })}
                    value={row.size}
                    list={listId}
                    maxLength={32}
                    required
                    disabled={saving || !canEdit}
                    onChange={(event) => setDraft((current) => current?.map((item) => item.id === row.id ? { ...item, size: event.target.value } : item) || null)}
                  />
                ) : row.size}</td>
                <td>{row.planned_quantity}</td><td>{row.completed_quantity}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {draft && (
          <>
            <datalist id={listId}>{GARMENT_SIZE_OPTIONS.map((size) => <option key={size} value={size} />)}</datalist>
            {!canEdit && <p className="mt-3 text-sm text-red-700" role="alert">{t("productionSizes.locked")}</p>}
            <div className="mt-3 flex justify-end gap-2">
              <button type="button" className="btn" disabled={saving} onClick={() => { setDraft(null); setError(""); }}>
                {t("btn.cancel")}
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving || !canEdit}>
                {saving ? t("common.saving") : t("btn.saveChanges")}
              </button>
            </div>
          </>
        )}
        {error && <p className="mt-3 text-sm text-red-700" role="alert">{error}</p>}
        {saved && <p className="mt-3 text-sm text-emerald-700" role="status">{t("productionSizes.saved")}</p>}
      </form>
    </div>
  );
}
