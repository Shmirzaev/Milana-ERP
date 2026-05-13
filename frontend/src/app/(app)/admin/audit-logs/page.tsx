"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function AuditLogsPage() {
  const { t } = useT();
  const params = useSearchParams();
  const initialEntity = params?.get("entity") ?? "";
  const initialId = params?.get("id") ?? "";
  const [entityFilter, setEntityFilter] = useState(initialEntity);
  const [idFilter, setIdFilter] = useState(initialId);
  const { data } = useSWR<any[]>("/api/audit-logs", fetcher);

  const rows = useMemo(() => {
    if (!data) return [];
    return data.filter((r) => {
      if (entityFilter && r.entity_type !== entityFilter) return false;
      if (idFilter && String(r.entity_id) !== idFilter) return false;
      return true;
    });
  }, [data, entityFilter, idFilter]);

  return (
    <div>
      <PageHeader title={t("page.admin.audit.title")} subtitle={t("page.admin.audit.subtitle")} />
      <div className="card p-3 mb-4 flex flex-wrap gap-3">
        <input className="input max-w-xs" placeholder="Filter by entity_type (e.g. ProductionOrder)" value={entityFilter} onChange={(e) => setEntityFilter(e.target.value)} />
        <input className="input max-w-xs" placeholder="Filter by entity_id" value={idFilter} onChange={(e) => setIdFilter(e.target.value)} />
        {(entityFilter || idFilter) && (
          <button className="btn" onClick={() => { setEntityFilter(""); setIdFilter(""); }}>Clear</button>
        )}
        <div className="text-xs text-slate-500 self-center">{rows.length} matches</div>
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.when")}</th>
              <th>{t("field.user")}</th>
              <th>{t("field.action")}</th>
              <th>{t("field.entity")}</th>
              <th>{t("field.id")}</th>
              <th>{t("field.value")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>{r.user_id || "-"}</td>
                <td>{r.action}</td>
                <td>{r.entity_type}</td>
                <td>{r.entity_id || "-"}</td>
                <td className="text-xs">
                  <pre>{JSON.stringify(r.new_value || r.old_value || {})}</pre>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
