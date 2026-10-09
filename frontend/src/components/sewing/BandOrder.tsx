"use client";
import { useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import DepartmentOrderList, { type DepartmentOrder } from "@/components/DepartmentOrderList";
import BandProgress from "./BandProgress";
import BandOutput from "./BandOutput";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { sewingBandText, type BandJob } from "@/lib/sewingBandText";

export default function BandOrder() {
  const { id } = useParams<{ id: string }>(); const params = useSearchParams();
  const { t, lang } = useT(); const text = sewingBandText(lang);
  const { data, error, mutate } = useSWR<(BandJob & DepartmentOrder)[]>("/api/sewing-bands/orders", fetcher, { refreshInterval: 10000 });
  const [output, setOutput] = useState<BandJob | null>(null);
  const jobs = (data || []).filter(j => j.work_order_id === Number(id) && (!params.get("assignment") || j.id === Number(params.get("assignment"))));
  return <div>
    <PageHeader title={`${text.floor} · ${jobs[0]?.order_no || ""}`} />
    {error && <p role="alert" className="text-red-700">{String(error)}</p>}
    {!data && !error ? <p>{text.loading}</p> : <>
      <DepartmentOrderList rows={jobs} title={text.order} emptyLabel={t("page.deptInbox.noOrders")} t={t} orderHref={row => `/work-orders/${row.work_order_id}/sewing?assignment=${row.sewing_assignment_id}`} />
      <section className="card mt-4 p-4"><BandProgress jobs={jobs} onOutput={setOutput} /></section>
    </>}
    <BandOutput job={output} onClose={() => setOutput(null)} onSaved={() => { void mutate(); }} />
  </div>;
}
