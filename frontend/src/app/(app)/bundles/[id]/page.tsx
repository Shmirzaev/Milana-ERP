"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function BundleDetail() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data: b } = useSWR<any>(`/api/bundles/${id}`, fetcher);

  if (!b) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader
        title={t("page.bundleDetail.title", { no: b.bundle_no })}
        subtitle={t("page.bundleDetail.subtitle", { status: b.status })}
        actions={<button type="button" className="btn" onClick={() => api.openLabel(`/api/bundles/${b.id}/label`)}>{t("btn.printLabel")}</button>}
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="card p-4">
          <h3 className="mb-2 font-medium">{t("page.bundleDetail.details")}</h3>
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.barcode")}</dt><dd><code>{b.barcode}</code></dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.bundleDetail.productionOrder")}</dt><dd>{b.production_order_id}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.bundleDetail.mcs")}</dt><dd>{b.model_id} / {b.color} / {b.size}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.quantity")}</dt><dd>{b.quantity}</dd></div>
          </dl>
          {b.qr_code_url && <img className="mt-3 w-40" src={b.qr_code_url} alt="QR" />}
        </div>
        <div className="card p-4">
          <h3 className="mb-2 font-medium">{t("page.bundleDetail.history")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.when")}</th>
                <th>{t("field.type")}</th>
                <th>{t("field.from")}</th>
                <th>{t("field.to")}</th>
                <th>{t("field.who")}</th>
              </tr>
            </thead>
            <tbody>
              {b.scan_logs?.map((s: any) => (
                <tr key={s.id}>
                  <td>{new Date(s.scanned_at).toLocaleString()}</td>
                  <td>{s.scan_type}</td>
                  <td>{s.from_department_id || "-"}</td>
                  <td>{s.to_department_id || "-"}</td>
                  <td>{s.scanned_by || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
