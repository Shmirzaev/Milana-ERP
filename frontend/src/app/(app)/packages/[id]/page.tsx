"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";

export default function PackageDetail() {
  const { t } = useT();
  const { me } = useMe();
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data: p } = useSWR<any>(
    `/api/packages/${id}`,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const canTraceability = can(me, "traceability.view");

  if (!p) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader
        title={t("page.packageDetail.title", { no: p.package_no })}
        subtitle={t("page.packageDetail.subtitle", { status: statusLabel(p.status, t) })}
        actions={(
          <>
            <button type="button" className="btn" onClick={() => api.openLabel(`/api/packages/${p.id}/label`)}>{t("btn.printLabel")}</button>
            {canTraceability && (
              <Link className="btn" href={`/traceability?package=${encodeURIComponent(p.package_no || p.barcode || p.id)}`}>
                {t("nav.traceability")}
              </Link>
            )}
          </>
        )}
      />
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="card p-4">
          <h3 className="mb-2 font-medium">{t("page.packageDetail.details")}</h3>
          <dl className="space-y-1 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.barcode")}</dt><dd><code>{p.barcode}</code></dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.packageDetail.productionOrder")}</dt><dd>{p.production_order_id}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("page.packageDetail.mc")}</dt><dd>{p.model_id} / {p.color}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.totalQty")}</dt><dd>{p.total_quantity}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.capacity")}</dt><dd>{p.capacity}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.weightKg")}</dt><dd>{p.weight_kg != null ? `${p.weight_kg} kg` : "-"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.cell")}</dt><dd>{p.storage_cell || "-"}</dd></div>
            <div className="flex justify-between"><dt className="text-slate-500">{t("field.shelf")}</dt><dd>{p.storage_shelf || "-"}</dd></div>
          </dl>
          <h4 className="mb-1 mt-3 font-medium">{t("page.packageDetail.sizes")}</h4>
          <ul className="text-sm">{p.items?.map((i: any) => <li key={i.id}>{i.size}: {i.quantity}</li>)}</ul>
          {p.qr_code_url && <img className="mt-3 w-40" src={p.qr_code_url} alt="QR" />}
        </div>
        <div className="card p-4">
          <h3 className="mb-2 font-medium">{t("page.packageDetail.scanHistory")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.when")}</th>
                <th>{t("field.type")}</th>
                <th>{t("field.who")}</th>
              </tr>
            </thead>
            <tbody>
              {p.scan_logs?.map((s: any) => (
                <tr key={s.id}>
                  <td>{new Date(s.scanned_at).toLocaleString()}</td>
                  <td>{statusLabel(s.scan_type, t)}</td>
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
