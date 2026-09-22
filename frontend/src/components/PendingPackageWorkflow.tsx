"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { isPackagePrintRun, pendingPackageWorkflow, postPackageWorkflow, packageWorkflowCopy, restorePendingPackageWorkflow, type PackagePrintRun } from "@/lib/packageWorkflow";

export default function PendingPackageWorkflow({ path, onResolved }: { path: string; onResolved: () => void | Promise<void> }) {
  const { me } = useMe();
  const { lang } = useT();
  const c = packageWorkflowCopy[lang];
  const [pending, setPending] = useState<Record<string, any> | null>(() => me?.id ? pendingPackageWorkflow(path, me.id)?.body || null : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resolvedError, setResolvedError] = useState("");
  useEffect(() => {
    const update = () => setPending(me?.id ? pendingPackageWorkflow(path, me.id)?.body || null : null);
    update();
    window.addEventListener("package-request-changed", update);
    return () => window.removeEventListener("package-request-changed", update);
  }, [me?.id, path]);
  if (!me || (!pending && !resolvedError)) return null;
  const count = pending?.packages?.length || pending?.package_ids?.length || 0;
  return <div className="my-3 border p-3">
    <p role="status">{resolvedError || `${c.pendingRequest} ${count} ${c.packages}`}</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {pending && <button className="btn mt-2" type="button" disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try {
        if (!pending) return;
        const savedRequest = pendingPackageWorkflow(path, me.id);
        const run = await postPackageWorkflow<PackagePrintRun>(path, pending, me.id);
        if (!isPackagePrintRun(run)) {
          if (savedRequest) restorePendingPackageWorkflow(path, me.id, savedRequest);
          throw new Error("The package receipt response was incomplete; the saved request is ready to retry.");
        }
        setPending(null); setResolvedError(c.received);
        try {
          await onResolved();
        } catch (e: any) {
          // The receipt is already committed and retrying would duplicate it.
          // Keep the resolved state visible while surfacing refresh failures.
          setError(e?.message || "The receipt was saved, but the page could not refresh.");
        }
        try {
          await api.openLabel(`/api/packages/print-runs/${run.id}/label`);
        } catch (e: any) {
          setResolvedError(c.labelUnavailable);
          setError(e.message);
        }
      } catch (e: any) { setError(e.message); }
      finally { setBusy(false); }
    }}>{busy ? c.loading : c.retry}</button>}
  </div>;
}
