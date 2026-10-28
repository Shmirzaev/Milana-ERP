"use client";
import { useState } from "react";
import { useT } from "@/lib/i18n";
import { shipmentReviewText } from "@/lib/shipmentReviewText";
import { shipmentDisplayText } from "@/lib/shipmentDisplay";

export default function ShipmentInvoiceActions({ shipmentId }: { shipmentId: number }) {
  const { lang } = useT();
  const [showPrices, setShowPrices] = useState(true);
  const query = `lang=${lang}&show_prices=${showPrices}`;
  return <>
    <button type="button" className="btn" onClick={() => setShowPrices(value => !value)}>{showPrices ? shipmentReviewText[lang].hidePrices : shipmentReviewText[lang].showPrices}</button>
    <a className="btn" href={`/api/shipments/${shipmentId}/invoice/print?${query}`} target="_blank" rel="noreferrer" title={shipmentReviewText[lang].reference}>{shipmentReviewText[lang].print}</a>
    <a className="btn" href={`/api/shipments/${shipmentId}/invoice.xlsx?${query}`} download>{shipmentDisplayText[lang].excel}</a>
  </>;
}
