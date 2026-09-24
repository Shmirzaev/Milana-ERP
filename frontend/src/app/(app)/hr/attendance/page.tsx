"use client";

import { useState } from "react";
import useSWRInfinite from "swr/infinite";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { HrHeader, LoadState, MetricGrid } from "@/components/hr/HrUi";

const PAGE_SIZE = 50;
type Row = { employee_id: number; employee_no: string | null; full_name: string; arrival_at: string | null; departure_at: string | null; worked_minutes: number; scheduled_minutes: number; variance_minutes: number; status: string };
type Summary = { employees: number; present: number; absent: number; overtime_minutes: number };
type AttendancePage = { day: string; summary: Summary; rows: Row[]; total: number; page: number; page_size: number; has_more: boolean; search: string };

function duration(minutes: number) {
  const sign = minutes < 0 ? "−" : "";
  const value = Math.abs(minutes);
  return `${sign}${Math.floor(value / 60)}h ${value % 60}m`;
}

export default function HrAttendancePage() {
  const { t } = useT();
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [search, setSearch] = useState("");
  const { data: pages, error, isLoading, isValidating, mutate, setSize } = useSWRInfinite<AttendancePage>(
    (index, previousPage) => {
      if (previousPage && !previousPage.has_more) return null;
      const params = new URLSearchParams({ day, page: String(index + 1), page_size: String(PAGE_SIZE), search });
      return `/api/hr/attendance?${params.toString()}`;
    },
    fetcher,
  );
  const rows = pages?.flatMap((page) => page.rows) ?? [];
  const firstPage = pages?.[0];
  const lastPage = pages?.[pages.length - 1];

  function changeDay(value: string) {
    setDay(value);
    void setSize(1);
  }

  function changeSearch(value: string) {
    setSearch(value);
    void setSize(1);
  }

  return <div>
    <HrHeader title="Attendance & Time Tracking" subtitle="Scheduled versus actual hours from fingerprint, face, RFID and turnstile events." actions={<button className="btn" onClick={() => void mutate()}>Refresh</button>} />
    <div className="card mb-4 grid gap-4 p-4 sm:grid-cols-2">
      <label><span className="label">Working date</span><input className="input" type="date" value={day} onChange={(event) => changeDay(event.target.value)} /></label>
      <label><span className="label">{t("common.search")}</span><input className="input" type="search" aria-label={t("common.search")} value={search} onChange={(event) => changeSearch(event.target.value)} placeholder={t("common.search")} /></label>
    </div>
    <MetricGrid items={[
      { label: "Employees", value: firstPage?.summary.employees ?? "—" },
      { label: "Present", value: firstPage?.summary.present ?? "—" },
      { label: "Absent", value: firstPage?.summary.absent ?? "—" },
      { label: "Overtime", value: firstPage ? duration(firstPage.summary.overtime_minutes) : "—" },
    ]} />
    {firstPage && <p className="mb-3 text-sm text-[#6d6757]">Loaded {rows.length} of {firstPage.total} employees{search ? ` matching “${search}”` : ""}.</p>}
    <LoadState loading={isLoading} error={error} empty={!isLoading && rows.length === 0}>
      <div className="card overflow-x-auto">
        <table className="table min-w-[850px]">
          <thead><tr><th>Employee</th><th>Employee ID</th><th>Arrival</th><th>Departure</th><th className="text-right">Scheduled</th><th className="text-right">Actual</th><th className="text-right">Variance</th><th>Status</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.employee_id}>
            <td className="font-medium">{row.full_name}</td>
            <td className="font-mono">{row.employee_no || `EMP-${row.employee_id}`}</td>
            <td>{row.arrival_at ? new Date(row.arrival_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</td>
            <td>{row.departure_at ? new Date(row.departure_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</td>
            <td className="text-right tabular-nums">{duration(row.scheduled_minutes)}</td>
            <td className="text-right tabular-nums">{duration(row.worked_minutes)}</td>
            <td className={`text-right font-semibold tabular-nums ${row.variance_minutes < 0 ? "text-red-700" : "text-emerald-700"}`}>{duration(row.variance_minutes)}</td>
            <td><span className={`badge ${row.status === "present" ? "badge-green" : "badge-red"}`}>{row.status}</span></td>
          </tr>)}</tbody>
        </table>
        {lastPage?.has_more && <button className="btn mt-3" onClick={() => void setSize((pages?.length ?? 1) + 1)} disabled={isValidating}>{t("common.loadMore")}</button>}
      </div>
    </LoadState>
  </div>;
}
