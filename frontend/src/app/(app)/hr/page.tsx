"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { HrHeader, LoadState, MetricGrid } from "@/components/hr/HrUi";

type Dashboard = { headcount: number; inactive: number; approved_positions: number; vacancies: number; candidates: number; upcoming_events: number; by_department: { name: string; count: number }[] };

export default function HrDashboardPage() {
  const { data, error, isLoading } = useSWR<Dashboard>("/api/hr/dashboard", fetcher);
  return <div>
    <HrHeader title="HR Dashboard" subtitle="Workforce, staffing, recruitment and upcoming HR activity." />
    <LoadState loading={isLoading} error={error}>
      {data && <>
        <MetricGrid items={[
          { label: "Active headcount", value: data.headcount },
          { label: "Vacant positions", value: data.vacancies, hint: `${data.approved_positions} approved positions` },
          { label: "Candidates", value: data.candidates },
          { label: "Upcoming events", value: data.upcoming_events },
        ]} />
        <div className="card p-5">
          <h2 className="text-base font-semibold">Headcount by department</h2>
          <div className="mt-4 space-y-3">
            {data.by_department.map((row) => <div key={row.name} className="grid grid-cols-[minmax(140px,240px)_1fr_50px] items-center gap-3 text-sm">
              <span>{row.name}</span><div className="h-2 overflow-hidden rounded bg-[#ecebe3]"><div className="h-full bg-[#14110b]" style={{ width: `${Math.max(3, row.count / Math.max(1, data.headcount) * 100)}%` }} /></div><span className="text-right tabular-nums">{row.count}</span>
            </div>)}
          </div>
        </div>
      </>}
    </LoadState>
  </div>;
}
