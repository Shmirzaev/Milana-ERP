"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

function Card({ title, value, sub }: { title: string; value: any; sub?: string }) {
  return (
    <div className="card p-5">
      <div className="text-xs text-slate-500 uppercase tracking-wide">{title}</div>
      <div className="text-2xl font-semibold mt-1">{value ?? "—"}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

export default function HomePage() {
  const { me } = useMe();
  const { t } = useT();
  const { data: mgmt } = useSWR<any>("/api/dashboard/management", fetcher);
  const { data: prod } = useSWR<any>("/api/dashboard/production", fetcher);
  const { data: fin } = useSWR<any>(can(me, "finance.view", "*") ? "/api/dashboard/finance" : null, fetcher);

  return (
    <div>
      <PageHeader
        title={`${t("common.welcome")}, ${me?.name || ""}`}
        subtitle={me?.role ? `${t("common.role")}: ${me.role}` : undefined}
      />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card title={t("dash.activeOrders")} value={mgmt?.active_orders} />
        <Card title={t("dash.lateOrders")} value={mgmt?.late_orders} />
        <Card title={t("dash.todaysDefects")} value={mgmt?.todays_defects} />
        <Card title={t("dash.todaysWaste")} value={mgmt?.todays_waste} sub={t("dash.todaysWasteSub")} />
      </div>
      <h2 className="text-lg font-semibold mb-3">{t("dash.production")}</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <Card title={t("dash.cutting")} value={prod?.cutting_output} />
        <Card title={t("dash.printing")} value={prod?.printing_output} />
        <Card title={t("dash.sewing")} value={prod?.sewing_output} />
        <Card title={t("dash.packaging")} value={prod?.packaging_output} />
      </div>
      {fin && (
        <>
          <h2 className="text-lg font-semibold mb-3">{t("dash.finance")}</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card title={t("dash.revenue")} value={`$${(fin.revenue_total || 0).toFixed(2)}`} />
            <Card title={t("dash.payments")} value={`$${(fin.payments_received || 0).toFixed(2)}`} />
            <Card title={t("dash.brandedValue")} value={`$${(fin.branded_stock_value || 0).toFixed(2)}`} />
            <Card title={t("dash.wasteIncome")} value={`$${(fin.waste_income || 0).toFixed(2)}`} />
          </div>
        </>
      )}
    </div>
  );
}
