"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { firstGradeText } from "@/lib/firstGradeText";
import type { PackagingSizeBalance } from "@/components/FirstGradePackaging";

export default function PackagingSizeEntry({ data, path, onSaved }: {
  data: PackagingSizeBalance; path: string; onSaved: () => Promise<unknown>;
}) {
  const { lang } = useT();
  const copy = firstGradeText[lang];
  const [counts, setCounts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const total = data.sizes.reduce((sum, row) => sum + Number(counts[row.size] || 0), 0);
  const valid = data.total > 0 && total === data.total && data.sizes.every(row => {
    const value = Number(counts[row.size] || 0);
    return Number.isInteger(value) && value >= row.packed;
  });
  return <form className="mt-3" onSubmit={async event => {
    event.preventDefault();
    if (busy || !valid) return;
    setBusy(true); setMessage("");
    try {
      await api.put(path, { version: data.version, sizes: data.sizes.map(row => ({ size: row.size, quantity: Number(counts[row.size] || 0) })) });
      await onSaved();
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }}>
    <p className="text-sm mb-3">{copy.sizeEntryHelp}</p>
    <div className="overflow-x-auto"><table className="table text-sm"><thead><tr>
      <th>{copy.size}</th><th>{copy.packed}</th><th>{copy.accepted}</th>
    </tr></thead><tbody>{data.sizes.map(row => <tr key={row.size}>
      <td>{row.size}</td><td>{row.packed}</td><td><input className="input w-28" type="number" step="1"
        min={row.packed} max={data.total} aria-label={`${copy.accepted} ${row.size}`} disabled={busy}
        value={counts[row.size] ?? ""} onChange={event => setCounts({ ...counts, [row.size]: event.target.value })} /></td>
    </tr>)}</tbody></table></div>
    <p className="my-3" role="status">{copy.total}: {total} / {data.total}</p>
    <button className="btn btn-primary" disabled={busy || !valid}>{copy.saveSizes}</button>
    {message && <p role="alert" className="mt-3 text-red-700">{message}</p>}
  </form>;
}
