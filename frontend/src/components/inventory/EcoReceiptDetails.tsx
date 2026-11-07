"use client";
import { useT } from "@/lib/i18n";
import { ecoReceiptText, type EcoReceiptDetails } from "@/lib/ecoReceipt";

export default function EcoReceiptDetailsView({ details, quantity }: {details?: EcoReceiptDetails; quantity: string}) {
  const { lang, t } = useT(); const text = ecoReceiptText(lang);
  if (!details || !Object.keys(details).length) return null;
  const rows = [
    [text.source, details.source ? text[details.source] : null], [text.document, details.document_no],
    [text.receivedDate, details.received_date ? new Date(details.received_date).toLocaleDateString(lang, {timeZone:"Asia/Tashkent"}) : null],
    [t("ph.supplier"), details.supplier_name], [t("ph.warehouse"), details.warehouse_name],
    [t("field.pieceCount"), details.piece_count], [t("field.oldCode"), details.old_code],
    [t("field.colorCode"), details.color_code], [t("field.colorStatus"), details.color_status],
    [text.width, details.width], [text.length, details.length_m], [t("field.gramaj"), details.gsm], [text.cost, details.cost_per_unit],
    [text.total, details.cost_per_unit ? (Number(quantity) * Number(details.cost_per_unit)).toLocaleString(lang, {maximumFractionDigits:4}) : null],
    [t("field.processes"), details.processes],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  return <details className="mt-2 text-sm"><summary className="cursor-pointer underline">{text.details}</summary>
    <dl className="my-2 grid grid-cols-2 gap-x-4 gap-y-1">{rows.map(([label,value]) => <div key={label} className="contents"><dt className="text-[var(--erp-muted)]">{label}</dt><dd>{value}</dd></div>)}</dl>
    {!!details.roll_weights_kg?.length && <table className="table my-2"><thead><tr><th>{t("field.pieceCount")}</th><th>kg</th><th>m</th></tr></thead><tbody>{details.roll_weights_kg.map((weight,index) => <tr key={index}><td>{index+1}</td><td>{weight}</td><td>{details.roll_lengths_m?.[index] || "—"}</td></tr>)}</tbody></table>}
    {details.image_url && <a className="underline" href={details.image_url} target="_blank" rel="noreferrer">{t("field.picture")}</a>}
  </details>;
}
