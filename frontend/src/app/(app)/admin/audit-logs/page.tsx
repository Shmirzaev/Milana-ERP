"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function AuditLogsPage() {
  const { t } = useT();
  const { data } = useSWR<any[]>("/api/audit-logs", fetcher);

  return (
    <div>
      <PageHeader title={t("page.admin.audit.title")} subtitle={t("page.admin.audit.subtitle")} />
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
            {data?.map((r) => (
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
