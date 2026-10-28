"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { isPackagePrintRun, packageWorkflowChangedEvent, pendingPackageWorkflow, reconcilePendingPackageWorkflow, packageWorkflowCopy, type PackagePrintRun } from "@/lib/packageWorkflow";

export default function PendingPackageWorkflow({ path, onResolved }: { path: string; onResolved: () => void | Promise<void> }) {
  const { me } = useMe();
  const { lang } = useT();
  const c = packageWorkflowCopy[lang];
  const [pending, setPending] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resolvedError, setResolvedError] = useState("");
  useEffect(() => {
    const update = () => {
      try {
        setPending(me?.id ? pendingPackageWorkflow(path, me.id)?.body || null : null);
      } catch (caught: any) {
        setPending(null);
        setError(caught?.message || "Package recovery storage is unavailable");
      }
    };
    update();
    window.addEventListener(packageWorkflowChangedEvent, update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener(packageWorkflowChangedEvent, update);
      window.removeEventListener("storage", update);
    };
  }, [me?.id, path]);
  if (!me || (!pending && !resolvedError && !error)) return null;
  const count = pending?.packages?.length || pending?.package_ids?.length || 0;
  return <div className="my-3 border p-3">
    <p role="status">{resolvedError || `${c.pendingRequest} ${count} ${c.packages}`}</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {pending && <button className="btn mt-2" type="button" disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try {
        if (!pending) return;
        const resolution = await reconcilePendingPackageWorkflow<PackagePrintRun>(path, me.id);
        setPending(null);
        if (resolution.status === "cancelled") {
          setResolvedError(c.pendingCancelled);
          return;
        }
        if (resolution.status === "completed_unavailable") {
          setResolvedError(c.resultUnavailable);
          return;
        }
        const run = resolution.result;
        if (!isPackagePrintRun(run)) {
          throw new Error("The recovered package receipt response was incomplete.");
        }
        setResolvedError(c.received);
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
    }}>{busy ? c.loading : c.recover}</button>}
  </div>;
}
