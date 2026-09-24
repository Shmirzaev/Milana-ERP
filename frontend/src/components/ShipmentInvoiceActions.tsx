"use client";
import { useT } from "@/lib/i18n";
import { shipmentReviewText } from "@/lib/shipmentReviewText";
import { shipmentDisplayText } from "@/lib/shipmentDisplay";

export default function ShipmentInvoiceActions({ shipmentId }: { shipmentId: number }) {
  const { lang } = useT();
  return <>
    <a className="btn" href={`/api/shipments/${shipmentId}/invoice/print?lang=${lang}`} target="_blank" rel="noreferrer" title={shipmentReviewText[lang].reference}>{shipmentReviewText[lang].print}</a>
    <a className="btn" href={`/api/shipments/${shipmentId}/invoice.xlsx?lang=${lang}`} download>{shipmentDisplayText[lang].excel}</a>
  </>;
}
