"use client";
import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

export default function FinishedGoodsPage() {
  const { t } = useT();
  const { data } = useSWR<any[]>("/api/finished-goods", fetcher, LIVE_DATA_SWR_OPTIONS);
  const { data: branded } = useSWR<any[]>(
    "/api/finished-goods/branded-stock",
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const { data: inbox } = useSWR<any>(
    "/api/inbox?dept=FGS",
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const readyToShip = Array.isArray(inbox?.ready_to_ship) ? inbox.ready_to_ship : [];
  return (
    <div>
      <PageHeader title={t("page.finishedGoods.title")} subtitle={t("page.finishedGoods.subtitle")} />
      <h2 className="text-lg font-medium mt-2 mb-2">{t("page.finishedGoods.branded")}</h2>
      <div className="card mb-6 overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.brand")}</th><th>{t("field.model")}</th><th>{t("field.color")}</th>
              <th>{t("field.size")}</th><th>{t("field.available")}</th><th>{t("field.reserved")}</th><th>{t("field.cost")}</th>
            </tr>
          </thead>
          <tbody>{branded?.map((s) => <tr key={s.id}><td>{s.brand_name || s.brand_id || "-"}</td><td>{s.model_code || s.model_id}</td><td>{s.color}</td><td>{s.size}</td><td>{s.available_qty}</td><td>{s.reserved_qty}</td><td>${Number(s.cost_per_piece).toFixed(2)}</td></tr>)}</tbody>
        </table>
      </div>
      <h2 className="text-lg font-medium mt-2 mb-2">{t("page.finishedGoods.all")}</h2>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.model")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th>
              <th>{t("field.qty")}</th><th>{t("field.available")}</th><th>{t("field.reserved")}</th>
              <th>{t("field.sold")}</th><th>{t("field.status")}</th>
            </tr>
          </thead>
          <tbody>{data?.map((s) => <tr key={s.id}><td>{s.model_code || s.model_id}</td><td>{s.color}</td><td>{s.size}</td><td>{s.quantity}</td><td>{s.available_qty}</td><td>{s.reserved_qty}</td><td>{s.sold_qty}</td><td>{statusLabel(s.status, t)}</td></tr>)}</tbody>
        </table>
      </div>
      <h2 className="text-lg font-medium mt-6 mb-2">{t("page.finishedGoods.readyToShip")}</h2>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr><th>{t("field.salesOrderShort")}</th><th>{t("field.customer")}</th><th>{t("field.packages")}</th><th>{t("field.qty")}</th><th>{t("field.shipmentNo")}</th></tr>
          </thead>
          <tbody>
            {readyToShip.map((row: any) => {
              const soId = Number(row.sales_order_id || 0);
              return (
                <tr key={row.sales_order_id || row.sales_order_no}>
                  <td>{row.sales_order_no || row.sales_order_id || "-"}</td>
                  <td>{row.customer_name || "-"}</td>
                  <td>{Number(row.packages || 0)}</td>
                  <td>{Number(row.quantity || 0)}</td>
                  <td>
                    {row.shipment_no ? (
                      <Link className="text-brand-600 hover:underline" href={`/shipments?so_id=${soId}&shipment_id=${row.shipment_id}`}>{row.shipment_no}</Link>
                    ) : soId ? (
                      <Link className="text-brand-600 hover:underline" href={`/shipments?so_id=${soId}`}>{t("page.finishedGoods.shipmentNotCreated")}</Link>
                    ) : "-"}
                  </td>
                </tr>
              );
            })}
            {readyToShip.length === 0 && <tr><td colSpan={5} className="text-sm text-slate-400">{t("page.finishedGoods.noOrdersReady")}</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
