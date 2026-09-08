"use client";
import useSWR from "swr";
import { useT } from "@/lib/i18n";
import { api, fetcher } from "@/lib/api";
import { packageWorkflowCopy, type PackagePrintRun } from "@/lib/packageWorkflow";
import { useState } from "react";

export default function PackagePrintRuns({ productionOrderId, refreshKey = 0 }: { productionOrderId?: number; refreshKey?: number }) {
  const { lang } = useT();
  const copy = packageWorkflowCopy[lang];
  const path = `/api/packages/print-runs${productionOrderId ? `?production_order_id=${productionOrderId}` : ""}`;
  const { data, error } = useSWR<PackagePrintRun[]>([path, refreshKey], ([url]: [string, number]) => fetcher(url));
  const [printError, setPrintError] = useState("");
  return <section className="mt-4 border-t pt-4">
    <h3 className="mb-3 font-medium">{copy.runs}</h3>
    {(error || printError) && <p role="alert" className="text-red-700">{printError || error.message}</p>}
    {!data && !error && <p>{copy.loading}</p>}
    {data?.length === 0 && <p>{copy.empty}</p>}
    {!!data?.length && <div className="overflow-x-auto"><table className="table text-sm"><thead><tr>
      <th>{copy.runs}</th><th>{copy.packages}</th><th>{copy.pieces}</th><th>{copy.status}</th><th>{copy.reprint}</th>
    </tr></thead><tbody>{data.map(run => <tr key={run.id}>
      <td>{run.run_no}<div className="text-xs text-slate-500">{new Date(run.created_at).toLocaleString(lang)}</div></td>
      <td>{run.count}</td><td>{run.quantity}</td><td>{run.received_at ? copy.complete : copy.pending}</td>
      <td><button type="button" className="btn" onClick={async () => {
        setPrintError("");
        try { await api.openLabel(`/api/packages/print-runs/${run.id}/label`); }
        catch (e: any) { setPrintError(e.message); }
      }}>{copy.reprint}</button></td>
    </tr>)}</tbody></table></div>}
  </section>;
}
