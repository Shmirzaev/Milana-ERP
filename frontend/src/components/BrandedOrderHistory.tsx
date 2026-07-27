"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ChevronDown, Plus, Search } from "lucide-react";
import ImageThumbnail from "@/components/ImageThumbnail";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

export type BrandedPlanningOrder = {
  id: number;
  order_no: string;
  ordered_for_type: string;
  customer_id?: number | null;
  ordered_for_name: string;
  status: string;
  created_at: string;
  production_count: number;
  total_quantity: number;
  productions: {
    id: number;
    order_no: string;
    production_no: string;
    model_id: number;
    planned_quantity: number;
    status: string;
  }[];
};

type ModelOption = {
  id: number;
  code?: string;
  name?: string;
  primary_image_url?: string | null;
  primary_image?: { file_url?: string | null } | null;
  variant_fabric?: string | null;
  fabric_image_url?: string | null;
};

export default function BrandedOrderHistory({
  orders,
  models,
  activeOrderId,
  creating,
  error,
  onNewOrder,
  onAddProduction,
}: {
  orders: BrandedPlanningOrder[];
  models: ModelOption[];
  activeOrderId: number;
  creating: boolean;
  error: string;
  onNewOrder: () => void;
  onAddProduction: (orderId: number) => void;
}) {
  const { t } = useT();
  const [searchText, setSearchText] = useState("");
  const [query, setQuery] = useState("");
  const modelById = useMemo(() => new Map(models.map((model) => [Number(model.id), model])), [models]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredOrders = useMemo(() => {
    return orders.flatMap((order) => {
      if (!normalizedQuery) return [{ ...order, visibleProductions: order.productions }];
      const orderMatches = order.order_no.toLocaleLowerCase().includes(normalizedQuery);
      const visibleProductions = orderMatches
        ? order.productions
        : order.productions.filter((production) => {
            const model = modelById.get(Number(production.model_id));
            return [
              production.order_no,
              production.production_no,
              production.status,
              model?.code,
              model?.name,
              model?.variant_fabric,
            ].some((value) => String(value || "").toLocaleLowerCase().includes(normalizedQuery));
          });
      return orderMatches || visibleProductions.length ? [{ ...order, visibleProductions }] : [];
    });
  }, [modelById, normalizedQuery, orders]);

  function submitSearch(event: React.FormEvent) {
    event.preventDefault();
    setQuery(searchText.trim());
  }

  function clearSearch() {
    setSearchText("");
    setQuery("");
  }

  return (
    <section className="card mb-6">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#ecebe3] px-5 py-4">
        <div>
          <h2 className="app-card-title">{t("page.planning.orderHistory")}</h2>
          <p className="mt-1 text-sm text-[#8a8472]">{t("page.planning.orderHistoryHelp")}</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={onNewOrder} disabled={creating}>
          <Plus />
          {creating ? t("common.creating") : t("page.planning.newOrder")}
        </button>
      </div>

      {error ? <div className="border-b border-[#ecebe3] px-5 py-3 text-sm text-red-700">{error}</div> : null}

      <form onSubmit={submitSearch} className="flex flex-col gap-2 border-b border-[#ecebe3] px-5 py-3 sm:flex-row">
        <label className="relative min-w-0 flex-1">
          <span className="sr-only">{t("common.search")}</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
          <input
            className="input pl-9"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder={t("page.planning.searchOrderHistory")}
          />
        </label>
        <button type="submit" className="btn btn-primary">
          <Search />
          {t("common.search")}
        </button>
        {query ? (
          <button type="button" className="btn" onClick={clearSearch}>{t("common.clear")}</button>
        ) : null}
      </form>

      {filteredOrders.length ? (
        <div className="divide-y divide-[#ecebe3]">
          {filteredOrders.map((order) => (
            <details
              key={order.id}
              className={`group ${order.id === activeOrderId ? "bg-[#faf9f5]" : ""}`}
              open={normalizedQuery ? true : undefined}
            >
              <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 hover:bg-[#faf9f5]">
                <ChevronDown className="h-4 w-4 shrink-0 text-[#8a8472] transition-transform group-open:rotate-180" />
                <span className="mono min-w-16 font-semibold text-[#14110b]">{order.order_no}</span>
                <span className="text-sm text-[#56503f]">
                  {t("page.planning.productionCount", { count: order.production_count })}
                </span>
                <span className="hidden text-sm text-[#8a8472] sm:inline">
                  {new Date(order.created_at).toLocaleDateString()}
                </span>
                <span className="ml-auto text-sm text-[#8a8472]">
                  {order.total_quantity.toLocaleString()} {t("field.qty").toLowerCase()}
                </span>
              </summary>

              <div className="border-t border-[#ecebe3] bg-[#faf9f5] px-5 py-4">
                {order.visibleProductions.length ? (
                  <div className="overflow-x-auto rounded-lg border border-[#e4e1d7] bg-white">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>{t("page.planning.productionOrder")}</th>
                          <th>{t("field.model")}</th>
                          <th>{t("page.planning.fabric")}</th>
                          <th>{t("field.qty")}</th>
                          <th>{t("field.status")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {order.visibleProductions.map((production) => {
                          const model = modelById.get(Number(production.model_id));
                          const modelLabel = model ? [model.code, model.name].filter(Boolean).join(" - ") : `#${production.model_id}`;
                          const fabricLabel = String(model?.variant_fabric || "").trim() || "-";
                          return (
                            <tr key={production.id}>
                              <td>
                                <Link className="mono font-semibold underline" href={`/production-orders/${production.id}`}>
                                  {production.order_no || production.production_no}
                                </Link>
                              </td>
                              <td>
                                <div className="flex min-w-56 items-center gap-3">
                                  <ImageThumbnail
                                    imageUrl={model?.primary_image?.file_url || model?.primary_image_url}
                                    label={modelLabel}
                                    title={t("page.workOrder.modelPicture")}
                                    emptyLabel={t("page.workOrder.noImage")}
                                  />
                                  <span>{modelLabel}</span>
                                </div>
                              </td>
                              <td>
                                <div className="flex min-w-48 items-center gap-3">
                                  <ImageThumbnail
                                    imageUrl={model?.fabric_image_url}
                                    label={fabricLabel}
                                    title={t("page.planning.fabricPicture")}
                                    emptyLabel={t("page.workOrder.noImage")}
                                  />
                                  <span>{fabricLabel}</span>
                                </div>
                              </td>
                              <td>{Number(production.planned_quantity || 0).toLocaleString()}</td>
                              <td>{statusLabel(production.status, t)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-sm text-[#8a8472]">{t("page.planning.noProductions")}</div>
                )}

                <div className="mt-4 flex justify-end">
                  <button type="button" className="btn" onClick={() => onAddProduction(order.id)}>
                    <Plus />
                    {t("page.planning.addProductionToThisOrder")}
                  </button>
                </div>
              </div>
            </details>
          ))}
        </div>
      ) : (
        <div className="px-5 py-8 text-center text-sm text-[#8a8472]">
          {normalizedQuery ? t("page.planning.noOrderSearchResults") : t("page.planning.noOrderHistory")}
        </div>
      )}
    </section>
  );
}
