"use client";
import Link from "next/link";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function PackagesPage() {
  const { t } = useT();
  const { data } = useSWR<any[]>("/api/packages", fetcher);

  return (
    <div>
      <PageHeader title={t("page.packages.title")} subtitle={t("page.packages.subtitle")} actions={<Link href="/packages/scan" className="btn">{t("btn.scan")}</Link>} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.packageNo")}</th>
              <th>{t("field.barcode")}</th>
              <th>{t("field.model")}</th>
              <th>{t("field.color")}</th>
              <th>{t("field.totalQty")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((p) => (
              <tr key={p.id}>
                <td className="font-medium">{p.package_no}</td>
                <td><code>{p.barcode}</code></td>
                <td>{p.model_id}</td>
                <td>{p.color}</td>
                <td>{p.total_quantity}</td>
                <td><span className="badge">{p.status}</span></td>
                <td className="flex gap-2">
                  <Link href={`/packages/${p.id}`} className="text-brand-600 hover:underline">{t("btn.view")}</Link>
                  <button type="button" className="text-slate-600 hover:underline" onClick={() => api.openLabel(`/api/packages/${p.id}/label`)}>{t("btn.label")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
