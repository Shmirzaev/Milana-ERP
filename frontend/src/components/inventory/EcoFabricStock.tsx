"use client";

import ImageThumbnail from "@/components/ImageThumbnail";
import EcoReceiptDetailsView from "@/components/inventory/EcoReceiptDetails";
import { ecoInventoryText, type EcoBatch } from "@/lib/ecoInventory";
import { ecoQualityText, ecoReceiptText } from "@/lib/ecoReceipt";
import { INVENTORY_QC_STATUSES, type InventoryQcStatus } from "@/lib/inventoryQcStatus";
import { useT } from "@/lib/i18n";

export default function EcoFabricStock({ rows, busy, uncertain, canUpdateQuality, canConsume, onQuality, onConsume }: {
  rows: EcoBatch[];
  busy: boolean;
  uncertain: boolean;
  canUpdateQuality: boolean;
  canConsume: boolean;
  onQuality: (row: EcoBatch, quality: InventoryQcStatus) => void;
  onConsume: (row: EcoBatch) => void;
}) {
  const { lang, t } = useT();
  const text = ecoInventoryText(lang);
  const receipt = ecoReceiptText(lang);
  const number = (value?: string | number | null) => value == null || value === "" ? "—"
    : Number(value).toLocaleString(lang === "uz" ? "uz-UZ" : lang === "ru" ? "ru-RU" : "en-GB", { maximumFractionDigits: 4 });
  const image = (row: EcoBatch) => <ImageThumbnail imageUrl={row.receipt_details?.image_url}
    label={`${row.item_name} · ${row.batch_no}`} title={t("field.picture")} emptyLabel={t("page.workOrder.noImage")} fit="contain" />;
  const quality = (row: EcoBatch) => canUpdateQuality ? <select className="input max-w-44"
    aria-label={`${receipt.inspection} ${row.batch_no}`} value={row.receipt_details?.qc_status || "passed"}
    disabled={busy} onChange={event => onQuality(row, event.target.value as InventoryQcStatus)}>
    {INVENTORY_QC_STATUSES.map(value => <option key={value} value={value}>{ecoQualityText(value, t, receipt)}</option>)}
  </select> : <span>{ecoQualityText(row.receipt_details?.qc_status || "passed", t, receipt)}</span>;
  const action = (row: EcoBatch) => canConsume && <button type="button" className="btn"
    disabled={busy || uncertain || Number(row.available_quantity) <= 0} onClick={() => onConsume(row)}>{text.consume}</button>;
  const colorDetails = (row: EcoBatch) => [
    [t("field.materialColor"), row.color], [t("field.colorCode"), row.receipt_details?.color_code],
    [t("field.colorStatus"), row.receipt_details?.color_status], [receipt.width, row.receipt_details?.width],
    [t("field.gramaj"), row.receipt_details?.gsm],
  ].filter(([, value]) => value != null && value !== "");

  if (!rows.length) return <p className="p-4 text-sm text-[#8a8472]">{text.empty}</p>;

  return <>
    <div className="divide-y divide-[#ecebe3] md:hidden">
      {rows.map(row => <article key={row.id} className="flex gap-3 p-4">
        <div className="shrink-0">{image(row)}</div>
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <div className="text-sm font-medium text-[#14110b]">{row.item_name}</div>
            <div className="mt-1 text-xs text-[#6f684f]">{text.batch}: <span className="mono text-[#14110b]">{row.batch_no}</span></div>
            <div className="mt-1 text-xs text-[#6f684f]">{row.sku}</div>
          </div>
          <dl className="space-y-1 text-xs">
            {colorDetails(row).map(([label, value]) => <div key={label} className="flex flex-wrap gap-x-1"><dt className="text-[#6f684f]">{label}:</dt><dd>{value}</dd></div>)}
            {row.receipt_details?.supplier_name && <div className="flex flex-wrap gap-x-1"><dt className="text-[#6f684f]">{t("field.supplier")}:</dt><dd>{row.receipt_details.supplier_name}</dd></div>}
            {row.receipt_details?.warehouse_name && <div className="flex flex-wrap gap-x-1"><dt className="text-[#6f684f]">{t("field.warehouse")}:</dt><dd>{row.receipt_details.warehouse_name}</dd></div>}
          </dl>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
            {[[text.balance, `${number(row.quantity)} ${row.unit}`], [text.reserved, `${number(row.reserved_quantity)} ${row.unit}`],
              [text.available, `${number(row.available_quantity)} ${row.unit}`], [receipt.cost, `${number(row.receipt_details?.cost_per_unit)} / ${row.unit}`]]
              .map(([label, value]) => <div key={label}><dt className="text-[#6f684f]">{label}</dt><dd className="mono mt-1">{value}</dd></div>)}
          </dl>
          <div className="flex flex-wrap items-center gap-2">{quality(row)}{action(row)}</div>
          <div className="overflow-x-auto"><EcoReceiptDetailsView details={row.receipt_details} quantity={row.quantity} /></div>
        </div>
      </article>)}
    </div>
    <div className="hidden overflow-x-auto md:block">
      <table className="table min-w-[1320px]">
        <thead><tr>
          <th>{t("field.picture")}</th><th>{text.batch} / {t("field.oldCode")}</th>
          <th>{t("common.name")} / {t("field.materialColor")}</th>
          <th>{text.balance}</th><th>{text.reserved}</th><th>{text.available}</th><th>{text.unit}</th>
          <th>{receipt.cost}</th><th>{t("field.supplier")} / {t("field.warehouse")}</th>
          <th>{receipt.document} / {receipt.inspection}</th>{canConsume && <th>{text.actions}</th>}
        </tr></thead>
        <tbody>{rows.map(row => <tr key={row.id}>
          <td>{image(row)}</td>
          <td className="min-w-[140px]"><div className="mono whitespace-nowrap font-semibold text-[#14110b]">{row.batch_no}</div>
            {row.receipt_details?.old_code && <div className="mt-1 text-xs text-[#6f684f]">{t("field.oldCode")}: {row.receipt_details.old_code}</div>}</td>
          <td className="min-w-[220px]">
            <div className="font-medium text-[#14110b]">{row.item_name}</div>
            <div className="mt-1 text-xs text-[#6f684f]">{row.sku}</div>
            <div className="mt-1 flex max-w-[280px] flex-wrap gap-x-3 gap-y-1 text-xs text-[#6f684f]">
              {colorDetails(row).map(([label, value]) => <span key={label}>{label}: <span className="text-[#14110b]">{value}</span></span>)}
            </div>
          </td>
          <td className="mono">{number(row.quantity)}</td><td className="mono">{number(row.reserved_quantity)}</td>
          <td className="mono">{number(row.available_quantity)}</td><td>{row.unit}</td>
          <td className="mono">{number(row.receipt_details?.cost_per_unit)}</td>
          <td className="min-w-[170px]"><div>{row.receipt_details?.supplier_name || "—"}</div>
            <div className="mt-1 text-xs text-[#6f684f]">{row.receipt_details?.warehouse_name || "—"}</div></td>
          <td className="min-w-[210px] space-y-2">
            {row.receipt_details?.document_no && <div className="text-xs text-[#6f684f]">{row.receipt_details.document_no}</div>}
            {quality(row)}<EcoReceiptDetailsView details={row.receipt_details} quantity={row.quantity} />
          </td>
          {canConsume && <td>{action(row)}</td>}
        </tr>)}</tbody>
      </table>
    </div>
  </>;
}
