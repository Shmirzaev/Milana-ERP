"use client";

import Link from "next/link";
import useSWR from "swr";
import { Check, ClipboardList, PackagePlus, RotateCcw, ShoppingBag, X } from "lucide-react";

import ForecastLineChart from "@/components/ForecastLineChart";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

function qty(value: unknown) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function ForecastingPage() {
  const { lang, t } = useT();
  const { me } = useMe();
  const canManage = can(me, "forecasting.manage");
  const { data, mutate } = useSWR<any>("/api/forecasting/dashboard", fetcher);
  const { data: recommendations, mutate: mutateRecommendations } = useSWR<any[]>("/api/forecasting/recommendations", fetcher);
  const branded = data?.branded_stock_suggestions || [];
  const reorder = data?.item_reorder_suggestions || [];
  const demandTrend = data?.demand_trend || [];
  const cards = data?.cards || {};
  const locale = lang === "ru" ? "ru-RU" : lang === "uz" ? "uz-UZ" : "en-US";
  const demandPoints = demandTrend.map((row: any) => ({
    label: new Intl.DateTimeFormat(locale, { month: "short", day: "numeric" }).format(new Date(`${row.week_start}T00:00:00`)),
    values: { demand: Number(row.quantity || 0) },
  }));
  const variantPoints = branded.slice(0, 8).map((row: any) => ({
    label: row.size || "-",
    tooltipLabel: `${row.model_code || row.model_id || "-"} / ${row.color || "-"} / ${row.size || "-"}`,
    values: {
      projected: Number(row.projected_demand || 0),
      available: Number(row.available_quantity || 0),
      suggested: Number(row.suggested_quantity || 0),
    },
  }));

  async function saveSuggestion(row: any) {
    await api.post("/api/forecasting/recommendations", {
      recommendation_type: row.recommendation_type,
      model_id: row.model_id || null,
      item_id: row.item_id || null,
      brand_id: row.brand_id || null,
      collection_id: row.collection_id || null,
      color: row.color || null,
      size: row.size || null,
      suggested_quantity: Number(row.suggested_quantity || 0),
      unit: row.unit || "pcs",
      confidence: row.confidence || null,
      reason: row.reason || null,
      source_json: row,
    });
    await mutateRecommendations();
  }

  async function setRecommendationStatus(id: number, status: "accepted" | "dismissed" | "converted") {
    await api.patch(`/api/forecasting/recommendations/${id}`, { status });
    await mutateRecommendations();
  }

  return (
    <div>
      <PageHeader
        title={t("page.forecasting.title")}
        subtitle={t("page.forecasting.subtitle")}
        actions={<button className="btn" onClick={() => mutate()}><RotateCcw />{t("btn.refresh")}</button>}
      />

      <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <div className="kpi-card"><div className="label">{t("page.forecasting.productionSuggestions")}</div><div className="mt-1 text-2xl font-semibold">{cards.suggested_production_count ?? branded.length}</div></div>
        <div className="kpi-card"><div className="label">{t("page.forecasting.reorderAlerts")}</div><div className="mt-1 text-2xl font-semibold">{cards.reorder_alert_count ?? reorder.length}</div></div>
        <div className="kpi-card"><div className="label">{t("page.forecasting.lowStockFinished")}</div><div className="mt-1 text-2xl font-semibold">{cards.low_stock_finished_goods ?? 0}</div></div>
        <div className="kpi-card"><div className="label">{t("page.forecasting.demandTrend")}</div><div className="mt-1 text-2xl font-semibold">{qty(cards.demand_trend_quantity)}</div></div>
      </div>

      <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ForecastLineChart
          title={t("page.forecasting.weeklyDemand")}
          description={t("page.forecasting.weeklyDemandDescription")}
          points={demandPoints}
          series={[{ key: "demand", label: t("page.forecasting.demand"), color: "var(--erp-accent)" }]}
          emptyLabel={t("page.forecasting.noChartData")}
          valueFormatter={(value) => qty(value)}
        />
        <ForecastLineChart
          title={t("page.forecasting.variantCoverage")}
          description={t("page.forecasting.variantCoverageDescription")}
          points={variantPoints}
          series={[
            { key: "projected", label: t("page.forecasting.projectedDemand"), color: "var(--erp-accent)" },
            { key: "available", label: t("page.forecasting.availableStock"), color: "var(--erp-success)" },
            { key: "suggested", label: t("page.forecasting.suggestedProduction"), color: "var(--erp-blue)" },
          ]}
          emptyLabel={t("page.forecasting.noChartData")}
          valueFormatter={(value) => qty(value)}
        />
      </div>

      <section className="card mb-5 overflow-x-auto">
        <div className="flex items-center justify-between gap-3 border-b border-[#ecebe3] p-4">
          <h2 className="app-card-title">{t("page.forecasting.brandedSuggestions")}</h2>
          <PackagePlus className="h-4 w-4 text-[#8a8472]" />
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.model")}</th>
              <th>{t("field.brand")}</th>
              <th>{t("field.color")}</th>
              <th>{t("field.size")}</th>
              <th>{t("page.forecasting.projectedDemand")}</th>
              <th>{t("field.available")}</th>
              <th>{t("page.forecasting.suggested")}</th>
              <th>{t("page.forecasting.confidence")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {branded.map((row: any) => (
              <tr key={`${row.model_id}-${row.brand_id}-${row.color}-${row.size}`}>
                <td><div className="font-medium">{row.model_code || row.model_id}</div><div className="text-xs text-[#8a8472]">{row.model_name || "-"}</div></td>
                <td>{row.brand_name || row.brand_id || "-"}</td>
                <td>{row.color}</td>
                <td>{row.size}</td>
                <td>{qty(row.projected_demand)}</td>
                <td>{qty(row.available_quantity)}</td>
                <td className="font-semibold">{qty(row.suggested_quantity)} {row.unit}</td>
                <td><span className="badge">{row.confidence}</span></td>
                <td className="flex flex-wrap gap-2">
                  <Link className="text-brand-600 hover:underline" href={`/planning?model_id=${row.model_id}&color=${encodeURIComponent(row.color || "")}&size=${encodeURIComponent(row.size || "")}&qty=${row.suggested_quantity}`}>
                    {t("page.forecasting.createPlan")}
                  </Link>
                  {canManage && <button className="text-slate-600 hover:underline" onClick={() => saveSuggestion(row)}>{t("page.forecasting.saveRecommendation")}</button>}
                </td>
              </tr>
            ))}
            {branded.length === 0 && <tr><td colSpan={9} className="text-sm text-slate-400">{t("page.forecasting.noBrandedSuggestions")}</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="card mb-5 overflow-x-auto">
        <div className="flex items-center justify-between gap-3 border-b border-[#ecebe3] p-4">
          <h2 className="app-card-title">{t("page.forecasting.reorderSuggestions")}</h2>
          <ShoppingBag className="h-4 w-4 text-[#8a8472]" />
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.item")}</th>
              <th>{t("field.category")}</th>
              <th>{t("field.available")}</th>
              <th>{t("field.reserved")}</th>
              <th>{t("page.forecasting.reorderLevel")}</th>
              <th>{t("page.forecasting.plannedDemand")}</th>
              <th>{t("page.forecasting.suggested")}</th>
              <th>{t("field.reason")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {reorder.map((row: any) => (
              <tr key={row.item_id}>
                <td><div className="font-medium">{row.item_sku}</div><div className="text-xs text-[#8a8472]">{row.item_name}</div></td>
                <td>{row.category}</td>
                <td>{qty(row.available_quantity)} {row.unit}</td>
                <td>{qty(row.reserved_quantity)} {row.unit}</td>
                <td>{qty(row.reorder_level)} {row.unit}</td>
                <td>{qty(row.planned_bom_demand)} {row.unit}</td>
                <td className="font-semibold">{qty(row.suggested_quantity)} {row.unit}</td>
                <td className="min-w-[260px] text-xs text-[#56503f]">{row.reason}</td>
                <td className="flex flex-wrap gap-2">
                  <Link className="text-brand-600 hover:underline" href={`/inventory?group=accessories&q=${encodeURIComponent(row.item_sku || "")}`}>
                    {t("page.forecasting.openInventory")}
                  </Link>
                  {canManage && <button className="text-slate-600 hover:underline" onClick={() => saveSuggestion(row)}>{t("page.forecasting.saveRecommendation")}</button>}
                </td>
              </tr>
            ))}
            {reorder.length === 0 && <tr><td colSpan={9} className="text-sm text-slate-400">{t("page.forecasting.noReorderSuggestions")}</td></tr>}
          </tbody>
        </table>
      </section>

      <section className="card overflow-x-auto">
        <div className="flex items-center justify-between gap-3 border-b border-[#ecebe3] p-4">
          <h2 className="app-card-title">{t("page.forecasting.savedRecommendations")}</h2>
          <ClipboardList className="h-4 w-4 text-[#8a8472]" />
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.type")}</th>
              <th>{t("field.status")}</th>
              <th>{t("page.forecasting.suggested")}</th>
              <th>{t("page.forecasting.confidence")}</th>
              <th>{t("field.reason")}</th>
              <th>{t("field.created")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {(recommendations || []).map((row) => (
              <tr key={row.id}>
                <td>{t(`forecast.type.${row.recommendation_type}`)}</td>
                <td><span className="badge">{statusLabel(row.status, t)}</span></td>
                <td>{qty(row.suggested_quantity)} {row.unit || ""}</td>
                <td>{row.confidence || "-"}</td>
                <td className="min-w-[280px] text-xs text-[#56503f]">{row.reason || "-"}</td>
                <td>{row.created_at ? new Date(row.created_at).toLocaleString() : "-"}</td>
                <td className="flex flex-wrap gap-2">
                  {canManage && row.status === "open" && (
                    <>
                      <button className="text-green-700 hover:underline" onClick={() => setRecommendationStatus(row.id, "accepted")}><Check className="inline h-3 w-3" /> {t("page.forecasting.accept")}</button>
                      <button className="text-red-700 hover:underline" onClick={() => setRecommendationStatus(row.id, "dismissed")}><X className="inline h-3 w-3" /> {t("page.forecasting.dismiss")}</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
            {(!recommendations || recommendations.length === 0) && <tr><td colSpan={7} className="text-sm text-slate-400">{t("page.forecasting.noSavedRecommendations")}</td></tr>}
          </tbody>
        </table>
      </section>
    </div>
  );
}
