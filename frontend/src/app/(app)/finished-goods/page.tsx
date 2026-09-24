"use client";
import { formatOrderReference } from "@/lib/orderRef";
import Link from "next/link";
import { useDeferredValue, useState } from "react";
import useSWRInfinite from "swr/infinite";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import StocktakeLink from "@/components/StocktakeLink";
import ShipmentItemLines from "@/components/ShipmentItemLines";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

const warehouseExitLabel = {
  en: "Create warehouse exit",
  ru: "Создать выдачу со склада",
  uz: "Ombor chiqimini yaratish",
} as const;

type FinishedGoodsStockPage = {
  rows: any[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

export default function FinishedGoodsPage() {
  const { lang, t } = useT();
  const [stockSearch, setStockSearch] = useState("");
  const [brandedSearch, setBrandedSearch] = useState("");
  const deferredStockSearch = useDeferredValue(stockSearch.trim());
  const deferredBrandedSearch = useDeferredValue(brandedSearch.trim());
  const {
    data: stockPages,
    size: stockSize,
    setSize: setStockSize,
    isValidating: stockValidating,
  } = useSWRInfinite<FinishedGoodsStockPage>(
    (index, previous) => previous && !previous.has_more
      ? null
      : `/api/finished-goods?page=${index + 1}&page_size=50&q=${encodeURIComponent(deferredStockSearch)}`,
    fetcher,
  );
  const {
    data: brandedPages,
    size: brandedSize,
    setSize: setBrandedSize,
    isValidating: brandedValidating,
  } = useSWRInfinite<FinishedGoodsStockPage>(
    (index, previous) => previous && !previous.has_more
      ? null
      : `/api/finished-goods/branded-stock?page=${index + 1}&page_size=50&q=${encodeURIComponent(deferredBrandedSearch)}`,
    fetcher,
  );
  const data = stockPages?.flatMap((page) => page.rows) ?? [];
  const branded = brandedPages?.flatMap((page) => page.rows) ?? [];
  const stockTotal = stockPages?.[0]?.total ?? 0;
  const brandedTotal = brandedPages?.[0]?.total ?? 0;
  const hasMoreStock = stockPages?.at(-1)?.has_more ?? false;
  const hasMoreBranded = brandedPages?.at(-1)?.has_more ?? false;
  const {
    data: readyToShipPages,
    size: readyToShipSize,
    setSize: setReadyToShipSize,
    isValidating: readyToShipValidating,
  } = useSWRInfinite<any>(
    (index) => `/api/inbox?dept=FGS&ready_to_ship_limit=50&ready_to_ship_offset=${index * 50}`,
    fetcher,
  );
  const readyToShip = readyToShipPages?.flatMap((page) => page?.ready_to_ship ?? []) ?? [];
  const readyToShipTotal = Number(readyToShipPages?.[0]?.ready_to_ship_total ?? 0);
  const hasMoreReadyToShip = readyToShip.length < readyToShipTotal;
  return (
    <div>
      <PageHeader
        title={t("page.finishedGoods.title")}
        subtitle={t("page.finishedGoods.subtitle")}
        actions={(
          <><StocktakeLink />
          <Link className="btn btn-primary" href="/shipments?mode=warehouse_exit">
            {warehouseExitLabel[lang]}
          </Link>
          </>
        )}
      />
      <h2 className="text-lg font-medium mt-2 mb-2">{t("page.finishedGoods.branded")}</h2>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="input h-8 min-w-48 flex-1"
          aria-label={`${t("common.search")} ${t("page.finishedGoods.branded")}`}
          placeholder={t("common.search")}
          value={brandedSearch}
          onChange={(event) => setBrandedSearch(event.target.value)}
        />
        <span className="text-xs text-slate-500">{branded.length} / {brandedTotal}</span>
      </div>
      <div className="card mb-6 overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.brand")}</th><th>{t("field.model")}</th><th>{t("field.color")}</th>
              <th>{t("field.size")}</th><th>{t("field.available")}</th><th>{t("field.reserved")}</th><th>{t("field.cost")}</th>
            </tr>
          </thead>
          <tbody>{branded.map((s) => <tr key={s.id}><td>{s.brand_name || s.brand_id || "-"}</td><td>{s.model_code || s.model_id}</td><td>{s.color}</td><td>{s.size}</td><td>{s.available_qty}</td><td>{s.reserved_qty}</td><td>${Number(s.cost_per_piece).toFixed(2)}</td></tr>)}</tbody>
        </table>
      </div>
      {hasMoreBranded && <button className="btn btn-secondary mb-6" disabled={brandedValidating} onClick={() => setBrandedSize(brandedSize + 1)}>{brandedValidating ? t("common.loading") : t("common.loadMore")}</button>}
      <h2 className="text-lg font-medium mt-2 mb-2">{t("page.finishedGoods.all")}</h2>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          className="input h-8 min-w-48 flex-1"
          aria-label={`${t("common.search")} ${t("page.finishedGoods.all")}`}
          placeholder={t("common.search")}
          value={stockSearch}
          onChange={(event) => setStockSearch(event.target.value)}
        />
        <span className="text-xs text-slate-500">{data.length} / {stockTotal}</span>
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.model")}</th><th>{t("field.color")}</th><th>{t("field.size")}</th>
              <th>{t("field.qty")}</th><th>{t("field.available")}</th><th>{t("field.reserved")}</th>
              <th>{t("field.sold")}</th><th>{t("field.status")}</th>
            </tr>
          </thead>
          <tbody>{data.map((s) => <tr key={s.id}><td>{s.model_code || s.model_id}</td><td>{s.color}</td><td>{s.size}</td><td>{s.quantity}</td><td>{s.available_qty}</td><td>{s.reserved_qty}</td><td>{s.sold_qty}</td><td>{statusLabel(s.status, t)}</td></tr>)}</tbody>
        </table>
      </div>
      {hasMoreStock && <button className="btn btn-secondary mt-3" disabled={stockValidating} onClick={() => setStockSize(stockSize + 1)}>{stockValidating ? t("common.loading") : t("common.loadMore")}</button>}
      <h2 className="text-lg font-medium mt-6 mb-2">{t("page.finishedGoods.readyToShip")}</h2>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr><th>{t("field.salesOrderShort")}</th><th>{t("field.customer")}</th><th>{t("field.address")}</th><th>{t("field.items")}</th><th>{t("field.packages")}</th><th>{t("field.qty")}</th><th>{t("field.shipmentNo")}</th></tr>
          </thead>
          <tbody>
            {readyToShip.map((row: any) => {
              const soId = Number(row.sales_order_id || 0);
              return (
                <tr key={row.sales_order_id || row.sales_order_no}>
                  <td>{formatOrderReference(row.sales_order_no || row.sales_order_id || "-")}</td>
                  <td>{row.customer_name || "-"}</td>
                  <td>{row.destination || row.customer_address || "-"}</td>
                  <td><ShipmentItemLines items={row.item_lines} /></td>
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
            {readyToShip.length === 0 && <tr><td colSpan={7} className="text-sm text-slate-400">{t("page.finishedGoods.noOrdersReady")}</td></tr>}
          </tbody>
        </table>
      </div>
      {hasMoreReadyToShip && (
        <button
          className="btn btn-secondary mt-3"
          disabled={readyToShipValidating}
          onClick={() => setReadyToShipSize(readyToShipSize + 1)}
        >
          {readyToShipValidating ? t("common.loading") : t("common.loadMore")}
        </button>
      )}
    </div>
  );
}
