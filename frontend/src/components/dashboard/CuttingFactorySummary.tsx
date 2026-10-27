"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { businessDate } from "./types";
import { departmentMessages } from "./departmentMessages";

export default function CuttingFactorySummary({ department }: { department: string }) {
  const { lang } = useT(); const c = departmentMessages[lang];
  const [period, setPeriod] = useState("week");
  const today = businessDate(); const day = new Date(`${today}T12:00:00Z`);
  if (period === "week") day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7);
  if (period === "month") day.setUTCDate(1);
  const { data, error, mutate } = useSWR<{ factories: { factory: string; bundles: number; pieces: number; created_bundles: number; created_pieces: number; transferred_bundles: number; transferred_pieces: number }[] }>(
    `/api/dashboard/cutting?cutting_department_code=${department}&start=${day.toISOString().slice(0, 10)}&end=${today}`, fetcher, { refreshInterval: 30_000 });
  return <section className="card mb-4 overflow-hidden"><div className="flex flex-wrap items-center justify-between gap-3 p-4"><h2 className="font-semibold">{c.all} · {c.factory}</h2><div role="group" aria-label={c.period} className="flex gap-1">{(["today", "week", "month"] as const).map(key => <button key={key} className={`btn ${period === key ? "btn-primary" : ""}`} aria-pressed={period === key} onClick={() => setPeriod(key)}>{c[key]}</button>)}</div></div>
    <p className="px-4 pb-3 text-xs text-slate-500">{c.balanceHelp}</p>
    {error && <p role="alert" className="px-4 pb-3 text-amber-800">{data ? c.stale : c.error} <button className="underline" onClick={() => void mutate()}>{c.refresh}</button></p>}
    <div className="overflow-x-auto"><table className="table"><thead><tr><th>{c.factory}</th><th>{c.current} · {c.bundles}</th><th>{c.current} · {c.pieces}</th><th>{c.created} · {c.period}</th><th>{c.transferred} · {c.period}</th></tr></thead><tbody>{data?.factories.map(row => <tr key={row.factory}><td><Link className="font-semibold hover:underline" href={`/cutting-inventory?cutting_department=${department}&destination_factory=${row.factory}`}>{row.factory === "MIL" ? "Milana" : row.factory === "BST" ? "Besttex" : row.factory === "ECO" ? "Eco Cotton" : c.unassigned}</Link></td><td>{row.bundles.toLocaleString()}</td><td>{row.pieces.toLocaleString()}</td><td>{row.created_bundles.toLocaleString()} {c.bundles} / {row.created_pieces.toLocaleString()} {c.pieces}</td><td>{row.transferred_bundles.toLocaleString()} {c.bundles} / {row.transferred_pieces.toLocaleString()} {c.pieces}</td></tr>)}</tbody></table></div>
  </section>;
}
