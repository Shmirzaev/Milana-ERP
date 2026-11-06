"use client";

import { Printer } from "lucide-react";
import ImageThumbnail from "@/components/ImageThumbnail";
import type { CtxT } from "@/lib/i18n";
import { besttexCuttingText } from "@/lib/besttexCutting";
import { formatOrderReference } from "@/lib/orderRef";
import { formatVariantNumber } from "@/lib/variantDisplay";

export type BesttexCutOrder = {
  cutting_record_id: number; cutting_batch_no: string | null; production_no: string; order_no: string;
  batch_no: string | null; model_code: string | null; model_name: string | null;
  planning_order_id: number | null; planning_order_no: string | null; planning_order_name: string | null;
  model_no: string | null; variant_no: string | null; model_image_url: string | null; variant_image_url: string | null;
  size_summary: string | null; material_label: string | null; deadline: string | null;
  cut_pieces: number; passed_pieces: number; created_at: string;
};

export default function BesttexCutOrderList({ rows, total, lang, t, printing, onPrint }: {
  rows: BesttexCutOrder[]; total: number; lang: keyof typeof besttexCuttingText; t: CtxT;
  printing: number | null; onPrint: (recordId: number) => void;
}) {
  const copy = besttexCuttingText[lang];
  const groups = new Map<string, BesttexCutOrder[]>();
  for (const row of rows) {
    const key = row.planning_order_id ? `bso-${row.planning_order_id}` : `po-${row.production_no}`;
    groups.set(key, [...(groups.get(key) || []), row]);
  }
  const date = (value: string) => new Date(value).toLocaleDateString(lang === "uz" ? "uz-UZ" : lang);
  return <section className="card min-w-0 overflow-hidden">
    <div className="border-b border-[#e3dfd3] px-4 py-2">
      <h2 className="app-card-title">{copy.title} ({total})</h2>
    </div>
    {Array.from(groups, ([key, orders]) => {
      const first = orders[0];
      const planningNumber = formatOrderReference(first.planning_order_no);
      const quantity = orders.reduce((sum, row) => sum + row.cut_pieces, 0);
      return <div key={key}>
        <div className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-1 border-y border-[#ecebe3] bg-[#f1efe8] px-4 py-2 text-sm">
          <span className="mono font-semibold text-[#14110b]">{first.planning_order_no
            ? /^BSO(?:[\s-]|$)/i.test(planningNumber) ? planningNumber : t("cuttingInbox.bsoNumber", { number: planningNumber })
            : t("cuttingInbox.orderNumber", { number: formatOrderReference(first.order_no) })}</span>
          {first.planning_order_name && <span className="text-[#56503f]">{first.planning_order_name}</span>}
          <span className="ml-auto text-xs text-[#8a8472]">{copy.pageSummary.replace("{orders}", String(orders.length)).replace("{qty}", quantity.toLocaleString())}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="table min-w-[1180px] [&_tbody_td]:!py-2 [&_thead_th]:!py-2" aria-label={copy.title}>
            <thead><tr>
              <th>{t("page.workOrder.modelPicture")}</th><th>{t("cuttingInbox.variantPicture")}</th>
              <th>{t("field.production")}</th><th>{t("field.modelNo")}</th><th>{t("field.variantNo")}</th>
              <th>{t("field.size")}</th><th>{t("cuttingInbox.material")}</th><th>{t("field.qty")}</th>
              <th>{copy.date}</th><th>{t("field.deadline")}</th><th className="text-right">{t("field.actions")}</th>
            </tr></thead>
            <tbody>{orders.map(row => <tr key={row.cutting_record_id} className="bg-yellow-50 hover:!bg-amber-100">
              <td><ImageThumbnail imageUrl={row.model_image_url} label={row.model_no || row.model_name || "—"} title={t("page.workOrder.modelPicture")} emptyLabel={t("page.workOrder.noImage")} /></td>
              <td><ImageThumbnail imageUrl={row.variant_image_url} label={formatVariantNumber(row.variant_no) || row.model_name || "—"} title={t("cuttingInbox.variantPicture")} emptyLabel={t("page.workOrder.noImage")} /></td>
              <td className="whitespace-nowrap"><span className="mono font-semibold text-[#14110b]">{formatOrderReference(row.production_no)}</span>
                <div className="text-xs text-[#56503f]">{row.cutting_batch_no || row.batch_no || "—"}</div></td>
              <td className="whitespace-nowrap" title={row.model_name || undefined}>{row.model_no || row.model_code || "—"}</td>
              <td className="whitespace-nowrap">{formatVariantNumber(row.variant_no) || "—"}</td>
              <td className="whitespace-nowrap">{row.size_summary || "—"}</td>
              <td className="max-w-64" title={row.material_label || undefined}><span className="block max-w-64 truncate">{row.material_label || "—"}</span></td>
              <td className="whitespace-nowrap">{copy.cut}: {row.cut_pieces.toLocaleString()}<div className="text-xs text-[#56503f]">{copy.passed}: {row.passed_pieces.toLocaleString()}</div></td>
              <td className="whitespace-nowrap">{date(row.created_at)}</td><td className="whitespace-nowrap">{row.deadline ? date(row.deadline) : "—"}</td>
              <td><div className="flex justify-end"><button type="button" className="btn btn-primary inline-flex h-8 items-center gap-2 whitespace-nowrap px-3 text-[11px]" disabled={printing !== null} onClick={() => onPrint(row.cutting_record_id)}>
                <Printer className="h-4 w-4" aria-hidden="true" />{copy.print}
              </button></div></td>
            </tr>)}</tbody>
          </table>
        </div>
      </div>;
    })}
    {!rows.length && <p className="px-4 py-6 text-sm text-[#8a8472]">{copy.empty}</p>}
  </section>;
}
