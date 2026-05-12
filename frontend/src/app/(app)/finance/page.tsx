"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

function Card({ title, value }: { title: string; value: any }) {
  return (
    <div className="card p-5">
      <div className="text-xs text-slate-500 uppercase tracking-wide">{title}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </div>
  );
}

export default function FinancePage() {
  const { t } = useT();
  const { data } = useSWR<any>("/api/finance/dashboard", fetcher);
  const { data: branded } = useSWR<any>("/api/finance/branded-stock-value", fetcher);
  const { data: waste } = useSWR<any>("/api/finance/waste-report", fetcher);
  return (
    <div>
      <PageHeader title={t("page.finance.title")} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <Card title={t("page.finance.revenue")} value={`$${Number(data?.revenue_total || 0).toFixed(2)}`} />
        <Card title={t("page.finance.paymentsReceived")} value={`$${Number(data?.payments_received || 0).toFixed(2)}`} />
        <Card title={t("page.finance.brandedValue")} value={`$${Number(branded?.value || 0).toFixed(2)}`} />
        <Card title={t("page.finance.wasteCostIncome")} value={`$${Number(waste?.cost || 0).toFixed(2)} / $${Number(waste?.income || 0).toFixed(2)}`} />
      </div>
    </div>
  );
}
