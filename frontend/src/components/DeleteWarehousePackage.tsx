"use client";
import { useState } from "react";
import { mutate } from "swr";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { useDialogs } from "@/components/DialogProvider";
import { warehousePackageText } from "@/lib/warehousePackageText";

export default function DeleteWarehousePackage({ id, packageNo }: { id: number; packageNo: string }) {
  const { me } = useMe(); const { lang } = useT(); const c = warehousePackageText[lang]; const dialogs = useDialogs();
  const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  if (!can(me, "storage.packages")) return null;
  return <><button className="btn text-red-700" type="button" disabled={busy} onClick={async () => {
    if (busy || !(await dialogs.ask({ message: `${packageNo}. ${c.deleteConfirm}` }))) return;
    setBusy(true); setError("");
    try {
      await api.del(`/api/packages/warehouse/${id}`);
      await mutate(key => typeof key === "string" && ["/api/packages", "/api/finished-goods", "/api/inbox"].some(prefix => key.startsWith(prefix)));
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setBusy(false); }
  }}>{c.delete}</button>{error && <p className="text-sm text-red-700" role="alert">{error}</p>}</>;
}
