"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";

import PageHeader from "@/components/PageHeader";
import { fetcher } from "@/lib/api";

const DEPT_LABELS: Record<string, string> = {
  CUT: "Cutting Floor",
  PRT: "Printing Floor",
  SEW: "Sewing Floor",
  PKG: "Packaging Floor",
  FGS: "Ready Storage",
};

function woActionLink(wo: any) {
  if (wo.operation === "cutting") return `/work-orders/${wo.id}/cutting`;
  if (wo.operation === "printing") return `/work-orders/${wo.id}/printing`;
  if (wo.operation === "sewing") return `/work-orders/${wo.id}/sewing`;
  if (wo.operation === "packaging") return `/work-orders/${wo.id}/packaging`;
  return `/production-orders/${wo.production_order_id}`;
}

export default function DepartmentInboxPage() {
  const params = useParams<{ code: string }>();
  const code = String(params.code || "").toUpperCase();
  const { data, isLoading } = useSWR<any>(code ? `/api/inbox?dept=${code}` : null, fetcher, {
    refreshInterval: 10_000,
  });

  return (
    <div>
      <PageHeader
        title={`${DEPT_LABELS[code] || code} Inbox`}
        subtitle="Incoming, in-progress, and finished work for your department"
      />
      {isLoading && <div className="card p-4 text-sm text-slate-500">Loading...</div>}
      {!isLoading && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <section className="card p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Incoming ({(data?.incoming_bundles || []).length})
            </h3>
            <div className="space-y-2">
              {(data?.incoming_bundles || []).map((b: any) => (
                <div key={b.id} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="font-medium">{b.bundle_no}</div>
                  <div className="text-xs text-slate-500">{b.color} / {b.size} / {b.quantity}</div>
                  <Link className="text-xs text-brand-600 hover:underline" href={`/bundles/${b.id}`}>Open bundle</Link>
                </div>
              ))}
              {(data?.incoming_bundles || []).length === 0 && <div className="text-sm text-slate-400">No incoming bundles</div>}
            </div>
          </section>

          <section className="card p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              In Progress ({(data?.active_work_orders || []).length})
            </h3>
            <div className="space-y-2">
              {(data?.active_work_orders || []).map((w: any) => (
                <div key={w.id} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="flex items-center justify-between">
                    <div className="font-medium">WO #{w.id} ({w.operation})</div>
                    <span className="badge">{w.status}</span>
                  </div>
                  <div className="text-xs text-slate-500">passed {w.passed_qty} / planned {w.planned_output_qty}</div>
                  <Link className="text-xs text-brand-600 hover:underline" href={woActionLink(w)}>Open</Link>
                </div>
              ))}
              {(data?.active_work_orders || []).length === 0 && <div className="text-sm text-slate-400">No active work orders</div>}
            </div>
          </section>

          <section className="card p-4">
            <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Done Today ({(data?.done_today || []).length})
            </h3>
            <div className="space-y-2">
              {(data?.done_today || []).map((w: any) => (
                <div key={w.id} className="rounded border border-slate-200 p-2 text-sm">
                  <div className="font-medium">WO #{w.id} ({w.operation})</div>
                  <div className="text-xs text-slate-500">passed {w.passed_qty}</div>
                  <Link className="text-xs text-brand-600 hover:underline" href={`/production-orders/${w.production_order_id}`}>View order</Link>
                </div>
              ))}
              {(data?.done_today || []).length === 0 && <div className="text-sm text-slate-400">Nothing completed in the last 24h</div>}
            </div>
          </section>
        </div>
      )}

      {code === "PKG" && data?.awaiting_packaging?.length > 0 && (
        <div className="card mt-4 p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">Awaiting Packaging</h3>
          <table className="table">
            <thead>
              <tr><th>Production</th><th>Ready qty</th><th>Sewn</th><th>Packed</th></tr>
            </thead>
            <tbody>
              {data.awaiting_packaging.map((r: any) => (
                <tr key={r.production_order_id}>
                  <td>{r.production_no || r.production_order_id}</td>
                  <td>{r.ready_qty}</td>
                  <td>{r.sewn_passed}</td>
                  <td>{r.already_packed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {code === "FGS" && (
        <div className="grid grid-cols-1 gap-4 mt-4 lg:grid-cols-2">
          <section className="card p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Pending Package Intake ({(data?.pending_packages || []).length})
            </h3>
            <table className="table">
              <thead><tr><th>Package</th><th>SO</th><th>Qty</th></tr></thead>
              <tbody>
                {(data?.pending_packages || []).map((p: any) => (
                  <tr key={p.id}><td>{p.package_no}</td><td>{p.sales_order_id || "â€”"}</td><td>{p.total_quantity}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
          <section className="card p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Ready To Ship ({(data?.ready_to_ship || []).length} orders)
            </h3>
            <table className="table">
              <thead><tr><th>SO</th><th>Packages</th><th>Qty</th></tr></thead>
              <tbody>
                {(data?.ready_to_ship || []).map((r: any, idx: number) => (
                  <tr key={`${r.sales_order_id}-${idx}`}><td>{r.sales_order_id || "â€”"}</td><td>{r.packages}</td><td>{r.quantity}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
