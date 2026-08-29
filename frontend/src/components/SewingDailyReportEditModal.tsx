"use client";

import { useEffect, useMemo, useState } from "react";
import { Save } from "lucide-react";

import DefectReasonSelect from "@/components/DefectReasonSelect";
import Modal from "@/components/Modal";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

export type EditableSewingReportRow = {
  id: number;
  report_date: string;
  work_order_id: number | null;
  line_code: string;
  line_name: string;
  order_no: string | null;
  model_code?: string | null;
  model_no?: string | null;
  variant_no?: string | null;
  manual_model_no: string | null;
  manual_variant_no: string | null;
  kroy_no: string | null;
  sewn_qty: number;
  section_quantities: number[] | null;
  section_no: number | null;
  section_name: string | null;
  top_qty: number | null;
  bottom_qty: number | null;
  defective_qty: number;
  defect_reason: string | null;
  notes: string | null;
};

type Props = {
  row: EditableSewingReportRow | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
};

export default function SewingDailyReportEditModal({ row, onClose, onSaved }: Props) {
  const { t } = useT();
  const [reportDate, setReportDate] = useState("");
  const [manualModelNo, setManualModelNo] = useState("");
  const [manualVariantNo, setManualVariantNo] = useState("");
  const [kroyNo, setKroyNo] = useState("");
  const [sewnQty, setSewnQty] = useState<NumberInputValue>("");
  const [sectionQuantities, setSectionQuantities] = useState<NumberInputValue[] | null>(null);
  const [sectionNo, setSectionNo] = useState<NumberInputValue>("");
  const [sectionName, setSectionName] = useState("");
  const [topQty, setTopQty] = useState<NumberInputValue>("");
  const [bottomQty, setBottomQty] = useState<NumberInputValue>("");
  const [defectiveQty, setDefectiveQty] = useState<NumberInputValue>("");
  const [defectReason, setDefectReason] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!row) return;
    setReportDate(row.report_date);
    setManualModelNo(row.manual_model_no || "");
    setManualVariantNo(row.manual_variant_no || "");
    setKroyNo(row.kroy_no || "");
    setSewnQty(row.sewn_qty);
    setSectionQuantities(row.section_quantities ? row.section_quantities.map(Number) : null);
    setSectionNo(row.section_no ?? "");
    setSectionName(row.section_name || "");
    setTopQty(row.top_qty ?? "");
    setBottomQty(row.bottom_qty ?? "");
    setDefectiveQty(row.defective_qty);
    setDefectReason(row.defect_reason || "");
    setNotes(row.notes || "");
    setError("");
  }, [row]);

  const usesThreeSections = sectionQuantities !== null;
  const usesTwoParts = Boolean(
    !usesThreeSections && row && row.top_qty !== null && row.bottom_qty !== null,
  );
  const correctedSewnQty = useMemo(() => {
    if (usesThreeSections) {
      return (sectionQuantities || []).reduce<number>(
        (total, quantity) => total + numberOrZero(quantity),
        0,
      );
    }
    if (usesTwoParts) return numberOrZero(topQty) + numberOrZero(bottomQty);
    return numberOrZero(sewnQty);
  }, [bottomQty, sectionQuantities, sewnQty, topQty, usesThreeSections, usesTwoParts]);

  async function saveCorrection() {
    if (!row) return;
    setError("");
    const defective = numberOrZero(defectiveQty);
    if (!reportDate) {
      setError(t("page.sewingDailyReport.selectDate"));
      return;
    }
    if (!row.work_order_id && !manualModelNo.trim()) {
      setError(t("page.sewingDailyReport.manualModelRequired"));
      return;
    }
    if (correctedSewnQty <= 0) {
      setError(t("page.sewingDailyReport.sewnRequired"));
      return;
    }
    if (defective < 0 || defective > correctedSewnQty) {
      setError(t("page.sewingDailyReport.defectiveRange"));
      return;
    }
    if (defective > 0 && !defectReason.trim()) {
      setError(t("page.sewingDailyReport.reasonRequired"));
      return;
    }

    setSaving(true);
    try {
      await api.patch(`/api/sewing-daily-reports/${row.id}`, {
        report_date: reportDate,
        manual_model_no: manualModelNo.trim() || null,
        manual_variant_no: manualVariantNo.trim() || null,
        kroy_no: kroyNo.trim() || null,
        sewn_qty: correctedSewnQty,
        section_quantities: sectionQuantities?.map(numberOrZero) || null,
        section_no: sectionNo === "" ? null : numberOrZero(sectionNo),
        section_name: sectionName.trim() || null,
        top_qty: usesTwoParts ? numberOrZero(topQty) : null,
        bottom_qty: usesTwoParts ? numberOrZero(bottomQty) : null,
        defective_qty: defective,
        defect_reason: defective > 0 ? defectReason.trim() || null : null,
        notes: notes.trim() || null,
      });
      await onSaved();
      onClose();
    } catch (updateError: any) {
      setError(updateError?.message || t("page.sewingDailyReport.updateFailed"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open={Boolean(row)}
      onClose={() => {
        if (!saving) onClose();
      }}
      title={t("page.sewingDailyReport.editTitle")}
      wide
      closeOnOutsideClick={false}
    >
      {row && (
        <div className="space-y-4">
          <div className="rounded-md border border-[#e3dfd3] bg-[#fbfaf6] px-3 py-2 text-sm text-[#56503f]">
            <span className="font-medium text-[#14110b]">{row.line_name}</span>
            <span> · {row.line_code}</span>
            {row.order_no && <span> · {row.order_no}</span>}
            <div className="mt-1 text-xs">{t("page.sewingDailyReport.editHint")}</div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="daily-report-edit-date">{t("field.date")}</label>
              <input
                id="daily-report-edit-date"
                className="input"
                type="date"
                value={reportDate}
                onChange={(event) => setReportDate(event.target.value)}
              />
            </div>
            {sectionNo !== "" && (
              <div>
                <label className="label" htmlFor="daily-report-edit-section">{t("field.section")}</label>
                <input
                  id="daily-report-edit-section"
                  className="input"
                  type="number"
                  min={1}
                  max={20}
                  value={sectionNo}
                  onChange={(event) => setSectionNo(parseNumberInput(event.target.value))}
                />
              </div>
            )}
            <div>
              <label className="label" htmlFor="daily-report-edit-model">{t("field.modelNo")}</label>
              <input
                id="daily-report-edit-model"
                className="input"
                value={manualModelNo}
                maxLength={64}
                placeholder={row.model_no || row.model_code || ""}
                onChange={(event) => setManualModelNo(event.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="daily-report-edit-variant">{t("field.variantNo")}</label>
              <input
                id="daily-report-edit-variant"
                className="input"
                value={manualVariantNo}
                maxLength={64}
                placeholder={row.variant_no || ""}
                onChange={(event) => setManualVariantNo(event.target.value)}
              />
            </div>
            <div>
              <label className="label" htmlFor="daily-report-edit-kroy">{t("field.kroyNo")}</label>
              <input
                id="daily-report-edit-kroy"
                className="input"
                value={kroyNo}
                maxLength={64}
                onChange={(event) => setKroyNo(event.target.value)}
              />
            </div>
            {sectionName && (
              <div>
                <label className="label" htmlFor="daily-report-edit-section-name">{t("field.section")}</label>
                <input
                  id="daily-report-edit-section-name"
                  className="input"
                  value={sectionName}
                  maxLength={64}
                  onChange={(event) => setSectionName(event.target.value)}
                />
              </div>
            )}
          </div>

          {usesThreeSections ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {(sectionQuantities || []).map((quantity, index) => (
                <div key={index}>
                  <label className="label" htmlFor={`daily-report-edit-quantity-${index}`}>
                    {t("field.section")} {index + 1}
                  </label>
                  <input
                    id={`daily-report-edit-quantity-${index}`}
                    className="input"
                    type="number"
                    min={0}
                    value={quantity}
                    onChange={(event) => {
                      const value = parseNumberInput(event.target.value);
                      setSectionQuantities((current) => (
                        current?.map((item, itemIndex) => (itemIndex === index ? value : item)) || null
                      ));
                    }}
                  />
                </div>
              ))}
            </div>
          ) : usesTwoParts ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="daily-report-edit-top">{t("page.sewingDailyReport.topQty")}</label>
                <input
                  id="daily-report-edit-top"
                  className="input"
                  type="number"
                  min={0}
                  value={topQty}
                  onChange={(event) => setTopQty(parseNumberInput(event.target.value))}
                />
              </div>
              <div>
                <label className="label" htmlFor="daily-report-edit-bottom">{t("page.sewingDailyReport.bottomQty")}</label>
                <input
                  id="daily-report-edit-bottom"
                  className="input"
                  type="number"
                  min={0}
                  value={bottomQty}
                  onChange={(event) => setBottomQty(parseNumberInput(event.target.value))}
                />
              </div>
            </div>
          ) : (
            <div>
              <label className="label" htmlFor="daily-report-edit-sewn">{t("page.sewingDailyReport.sewnQty")}</label>
              <input
                id="daily-report-edit-sewn"
                className="input"
                type="number"
                min={0}
                value={sewnQty}
                onChange={(event) => setSewnQty(parseNumberInput(event.target.value))}
              />
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="label" htmlFor="daily-report-edit-defective">
                {t("page.sewingDailyReport.defectiveQty")}
              </label>
              <input
                id="daily-report-edit-defective"
                className="input"
                type="number"
                min={0}
                value={defectiveQty}
                onChange={(event) => setDefectiveQty(parseNumberInput(event.target.value))}
              />
            </div>
            <div>
              <label className="label" htmlFor="daily-report-edit-reason">{t("field.defectReason")}</label>
              <DefectReasonSelect
                id="daily-report-edit-reason"
                value={defectReason}
                onChange={setDefectReason}
                required={numberOrZero(defectiveQty) > 0}
              />
            </div>
          </div>

          <div>
            <label className="label" htmlFor="daily-report-edit-notes">{t("field.notes")}</label>
            <textarea
              id="daily-report-edit-notes"
              className="input min-h-[82px] resize-y"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 border-t border-[#e3dfd3] pt-4">
            <button type="button" className="btn" onClick={onClose} disabled={saving}>
              {t("common.cancel")}
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void saveCorrection()} disabled={saving}>
              <Save />
              {saving ? t("common.saving") : t("common.save")}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
