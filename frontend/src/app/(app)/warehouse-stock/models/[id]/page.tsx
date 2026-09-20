"use client";
import { useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { firstGradeText } from "@/lib/firstGradeText";
import { statusLabel } from "@/components/StagePipeline";

type PackageRow = { id: number; package_no: string; barcode: string; production_no?: string; quantity: number; available: number; reserved: number; weight_kg?: number; status: string; received_at?: string; cell?: string; shelf?: string; items: { size: string; color: string; quantity: number }[] };
type Result = { model_code: string; model_name: string; total: number; page_size: number; packages: PackageRow[] };
export default function WarehouseModelPackages() {
  const { id } = useParams<{ id: string }>(); const search = useSearchParams(); const [page, setPage] = useState(1);
  const { lang, t } = useT(); const copy = firstGradeText[lang];
  const kind = search.get("stock_kind") === "first_grade" ? "first_grade" : "standard";
  const { data, error } = useSWR<Result>(`/api/packages/warehouse-model/${id}?stock_kind=${kind}&page=${page}`, fetcher);
  return <main className="space-y-4"><Link className="btn" href={`/warehouse-stock?stock_kind=${kind}`}>{copy.stock}</Link>
    <h1 className="app-page-title">{data?.model_code} {data?.model_name}</h1><h2>{copy.packages} · {kind === "first_grade" ? copy.title : copy.standard} {data ? `(${data.total})` : ""}</h2>
    {error && <p role="alert" className="text-red-700">{error.message}</p>}{!data && !error && <p>{copy.loading}</p>}
    {data && <><div className="card overflow-x-auto"><table className="table text-sm"><thead><tr><th>{copy.packages}</th><th>{copy.production}</th><th>{copy.contents}</th><th>{copy.total}</th><th>{copy.available}</th><th>{copy.reserved}</th><th>{copy.weight}</th><th>{copy.location}</th><th>{copy.status}</th><th>{copy.received}</th></tr></thead><tbody>
      {data.packages.map(pkg => <tr key={pkg.id}><td><Link className="underline" href={`/packages/${pkg.id}`}>{pkg.package_no}</Link><div className="text-xs text-slate-500">{pkg.barcode}</div></td><td>{pkg.production_no || "—"}</td><td>{pkg.items.map((item, index) => <div key={index}>{item.color} · {item.size} × {item.quantity}</div>)}</td><td>{pkg.quantity}</td><td>{pkg.available}</td><td>{pkg.reserved}</td><td>{pkg.weight_kg ?? "—"}</td><td>{[pkg.cell, pkg.shelf].filter(Boolean).join(" / ") || "—"}</td><td>{statusLabel(pkg.status, t)}</td><td>{pkg.received_at ? new Date(pkg.received_at).toLocaleString(lang) : "—"}</td></tr>)}
      {!data.packages.length && <tr><td colSpan={10}>{copy.empty}</td></tr>}
    </tbody></table></div><div className="flex items-center gap-3"><button className="btn" disabled={page === 1} onClick={() => setPage(page - 1)}>{copy.previous}</button><span>{page} / {Math.max(1, Math.ceil(data.total / data.page_size))}</span><button className="btn" disabled={page * data.page_size >= data.total} onClick={() => setPage(page + 1)}>{copy.next}</button></div></>}
  </main>;
}
