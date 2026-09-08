"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { pendingPackageWorkflow, postPackageWorkflow, packageWorkflowCopy, type PackagePrintRun } from "@/lib/packageWorkflow";

export default function PendingPackageWorkflow({ path, onResolved }: { path: string; onResolved: () => void | Promise<void> }) {
  const { me } = useMe();
  const { lang } = useT();
  const c = packageWorkflowCopy[lang];
  const [pending, setPending] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const update = () => setPending(me?.id ? pendingPackageWorkflow(path, me.id)?.body || null : null);
    update();
    window.addEventListener("package-request-changed", update);
    return () => window.removeEventListener("package-request-changed", update);
  }, [me?.id, path]);
  if (!pending || !me) return null;
  const count = pending.packages?.length || pending.package_ids?.length || 0;
  return <div className="my-3 border p-3">
    <p role="status">{c.pendingRequest} {count} {c.packages}</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    <button className="btn mt-2" type="button" disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try {
        const run = await postPackageWorkflow<PackagePrintRun>(path, pending, me.id);
        setPending(null); await onResolved();
        await api.openLabel(`/api/packages/print-runs/${run.id}/label`);
      } catch (e: any) { setError(e.message); }
      finally { setBusy(false); }
    }}>{busy ? c.loading : c.retry}</button>
  </div>;
}
