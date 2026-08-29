"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Printer } from "lucide-react";
import QRCode from "qrcode";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";
import { divideBatchQuantityByRollCount } from "@/lib/materialRollWeights";

export type MaterialQrStickerData = {
  batchId: number;
  materialName: string;
  batchNo: string;
  color: string;
  supplier: string;
  batchQuantity: number;
  pieceCount: number;
  searchValue: string;
};

function shown(value: string | null | undefined) {
  return String(value || "").trim() || "-";
}

function Sticker({
  data,
  qrSrc,
  rollNumber,
  weight,
}: {
  data: MaterialQrStickerData;
  qrSrc: string;
  rollNumber: number;
  weight: number;
}) {
  const { t } = useT();

  return (
    <div className="material-roll-label" aria-label={t("page.inventory.qrStickerPreview")}>
      <div className="material-roll-label-inner">
        <div className="material-roll-header">
          <div>{shown(data.materialName)}</div>
          <div>{shown(data.supplier)}</div>
        </div>
        <div className="material-roll-body">
          <dl>
            <div><dt>{t("page.inventory.labelBatchNo")}</dt><dd>{shown(data.batchNo)}</dd></div>
            <div><dt>{t("page.inventory.labelColor")}</dt><dd>{shown(data.color)}</dd></div>
            <div><dt>{t("page.inventory.labelQty")}</dt><dd>{weight.toFixed(2)} Kg</dd></div>
          </dl>
          {qrSrc ? <img src={qrSrc} alt={t("page.inventory.qrSticker")} /> : <div className="material-roll-qr-placeholder" />}
        </div>
        <div className="material-roll-code">B{data.batchId}-R{rollNumber}</div>
      </div>
    </div>
  );
}

export default function MaterialQrStickerModal({
  data,
  onClose,
}: {
  data: MaterialQrStickerData | null;
  onClose: () => void;
}) {
  const { t } = useT();
  const [previewRoll, setPreviewRoll] = useState(1);
  const [qrSources, setQrSources] = useState<string[]>([]);
  const [qrError, setQrError] = useState(false);
  const weights = useMemo(() => (
    data ? divideBatchQuantityByRollCount(data.batchQuantity, data.pieceCount) : []
  ), [data]);
  const rollCount = weights.length;

  useEffect(() => {
    if (!data) return;
    setPreviewRoll(1);
  }, [data]);

  const qrPayloads = useMemo(() => {
    if (!data || typeof window === "undefined") return [];
    return Array.from({ length: rollCount }, (_, index) => {
      const url = new URL("/inventory", window.location.origin);
      url.searchParams.set("group", "materials");
      url.searchParams.set("q", data.searchValue);
      url.searchParams.set("batch_id", String(data.batchId));
      url.searchParams.set("roll", String(index + 1));
      url.searchParams.set("roll_total", String(rollCount));
      return url.toString();
    });
  }, [data, rollCount]);

  useEffect(() => {
    setPreviewRoll((current) => Math.min(Math.max(1, current), rollCount));
  }, [rollCount]);

  useEffect(() => {
    let active = true;
    setQrSources([]);
    setQrError(false);
    Promise.all(qrPayloads.map((payload) => QRCode.toDataURL(payload, {
      errorCorrectionLevel: "M",
      margin: 1,
      width: 320,
      color: { dark: "#000000", light: "#ffffff" },
    })))
      .then((values) => { if (active) setQrSources(values); })
      .catch(() => { if (active) setQrError(true); });
    return () => { active = false; };
  }, [qrPayloads]);

  useEffect(() => {
    const finishPrint = () => document.body.classList.remove("material-qr-print-active");
    window.addEventListener("afterprint", finishPrint);
    return () => {
      window.removeEventListener("afterprint", finishPrint);
      document.body.classList.remove("material-qr-print-active");
    };
  }, []);

  function printLabels() {
    if (!data || qrSources.length !== rollCount) return;
    document.body.classList.add("material-qr-print-active");
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => window.print()));
  }

  const previewQrSrc = qrSources[previewRoll - 1] || "";
  const previewWeight = weights[previewRoll - 1] || 0;
  const qrReady = qrSources.length === rollCount;

  return (
    <>
      <Modal open={Boolean(data)} onClose={onClose} title={t("page.inventory.qrSticker")}>
        {data ? (
          <div>
            <div className="text-sm text-[#6f684f]">
              {t("page.inventory.batchWeightExpected")}: {data.batchQuantity.toFixed(2)} kg
            </div>
            <div className="mt-3 flex items-center justify-between gap-3">
              <div className="text-sm text-[#6f684f]">{t("page.inventory.rollStickerCount", { count: rollCount })}</div>
              <div className="flex items-center gap-1">
                <button type="button" className="icon-btn" title={t("common.previous")} disabled={previewRoll <= 1} onClick={() => setPreviewRoll((value) => Math.max(1, value - 1))}><ChevronLeft /></button>
                <div className="min-w-14 text-center font-mono text-sm text-[#14110b]">{previewRoll} / {rollCount}</div>
                <button type="button" className="icon-btn" title={t("common.next")} disabled={previewRoll >= rollCount} onClick={() => setPreviewRoll((value) => Math.min(rollCount, value + 1))}><ChevronRight /></button>
              </div>
            </div>
            <div className="mt-2 overflow-x-auto border border-[#ded9ca] bg-[#f5f2e9] p-4">
              <div className="mx-auto w-[360px] max-w-full"><Sticker data={data} qrSrc={previewQrSrc} rollNumber={previewRoll} weight={previewWeight} /></div>
            </div>
            {qrError ? <div className="mt-2 text-sm text-red-700">{t("page.inventory.qrStickerUnavailable")}</div> : null}
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="btn" onClick={onClose}>{t("common.close")}</button>
              <button type="button" className="btn btn-primary" onClick={printLabels} disabled={!qrReady}>
                <Printer />
                {t("common.print")}
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
      {typeof document !== "undefined" && data ? createPortal(
        <div className="material-qr-print-sheet" aria-hidden="true">
          {weights.map((weight, index) => <Sticker key={index} data={data} qrSrc={qrSources[index] || ""} rollNumber={index + 1} weight={weight} />)}
        </div>,
        document.body,
      ) : null}
      <style jsx global>{`
        .material-roll-label { box-sizing: border-box; container-type: inline-size; width: 100%; aspect-ratio: 3 / 2; overflow: hidden; padding: 2.5%; background: #fff; color: #000; font-family: Arial, Helvetica, sans-serif; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        .material-roll-label-inner { display: flex; box-sizing: border-box; height: 100%; flex-direction: column; overflow: hidden; border: 1px solid #000; padding: 4%; }
        .material-roll-header { display: grid; grid-template-columns: minmax(0, 1fr) max-content; gap: 4%; font-size: 4.3cqw; font-weight: 700; line-height: 1.05; text-transform: uppercase; }
        .material-roll-header > div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .material-roll-body { display: grid; min-height: 0; flex: 1; grid-template-columns: minmax(0, 1fr) 34%; align-items: center; gap: 4%; padding-top: 4%; }
        .material-roll-body dl { display: grid; gap: 4%; margin: 0; }
        .material-roll-body dl > div { display: grid; grid-template-columns: 43% minmax(0, 1fr); gap: 3%; font-size: 4cqw; font-weight: 700; line-height: 1.1; }
        .material-roll-body dt, .material-roll-body dd { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .material-roll-body img, .material-roll-qr-placeholder { display: block; width: 100%; aspect-ratio: 1; background: #fff; object-fit: contain; }
        .material-roll-code { font-size: 3.6cqw; font-weight: 700; line-height: 1; }
        .material-qr-print-sheet { display: none; }
        @media print {
          @page { size: 60mm 40mm; margin: 0; }
          body.material-qr-print-active { width: 60mm !important; margin: 0 !important; padding: 0 !important; }
          body.material-qr-print-active > *:not(.material-qr-print-sheet) { display: none !important; }
          body.material-qr-print-active > .material-qr-print-sheet { display: block !important; width: 60mm !important; margin: 0 !important; padding: 0 !important; }
          body.material-qr-print-active .material-roll-label { width: 60mm !important; height: 40mm !important; aspect-ratio: auto !important; padding: 1.5mm !important; break-after: page; }
          body.material-qr-print-active .material-roll-label-inner { border-width: 0.25mm !important; padding: 2mm !important; }
          body.material-qr-print-active .material-roll-header { gap: 2mm !important; font-size: 7.5pt !important; line-height: 1.05 !important; }
          body.material-qr-print-active .material-roll-body { grid-template-columns: minmax(0, 1fr) 18mm !important; gap: 2mm !important; padding-top: 1.6mm !important; }
          body.material-qr-print-active .material-roll-body dl { gap: 1.3mm !important; }
          body.material-qr-print-active .material-roll-body dl > div { grid-template-columns: 17mm minmax(0, 1fr) !important; gap: 0.8mm !important; font-size: 7.5pt !important; line-height: 1.08 !important; }
          body.material-qr-print-active .material-roll-body img, body.material-qr-print-active .material-roll-qr-placeholder { width: 18mm !important; height: 18mm !important; }
          body.material-qr-print-active .material-roll-code { font-size: 7pt !important; }
          body.material-qr-print-active .material-roll-label:last-child { break-after: auto; }
        }
      `}</style>
    </>
  );
}
