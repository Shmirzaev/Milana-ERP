"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function FinishedGoodsPage() {
  const { t } = useT();
  const { data } = useSWR<any[]>("/api/finished-goods", fetcher);
  const { data: branded } = useSWR<any[]>("/api/finished-goods/branded-stock", fetcher);
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
          <tbody>{branded?.map((s) => <tr key={s.id}><td>{s.brand_id}</td><td>{s.model_id}</td><td>{s.color}</td><td>{s.size}</td><td>{s.available_qty}</td><td>{s.reserved_qty}</td><td>${Number(s.cost_per_piece).toFixed(2)}</td></tr>)}</tbody>
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
          <tbody>{data?.map((s) => <tr key={s.id}><td>{s.model_id}</td><td>{s.color}</td><td>{s.size}</td><td>{s.quantity}</td><td>{s.available_qty}</td><td>{s.reserved_qty}</td><td>{s.sold_qty}</td><td>{s.status}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
