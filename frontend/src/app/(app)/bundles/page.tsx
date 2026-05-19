"use client";
import Link from "next/link";
import { Fragment, useMemo } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function BundlesPage() {
  const { t } = useT();
  const { data } = useSWR<any[]>("/api/bundles", fetcher);

  const grouped = useMemo(() => {
    const map = new Map<string, { key: string; items: any[]; totalQty: number }>();
    for (const b of data || []) {
      const key = b.production_no || `PO-${b.production_order_id}`;
      const group = map.get(key);
      if (group) {
        group.items.push(b);
        group.totalQty += Number(b.quantity || 0);
      } else {
        map.set(key, { key, items: [b], totalQty: Number(b.quantity || 0) });
      }
    }
    return Array.from(map.values());
  }, [data]);

  return (
    <div>
      <PageHeader title={t("page.bundles.title")} subtitle={t("page.bundles.subtitle")} actions={<Link href="/bundles/scan" className="btn">{t("btn.scan")}</Link>} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.bundleNo")}</th>
              <th>{t("field.productionNo")}</th>
              <th>{t("field.barcode")}</th>
              <th>{t("field.model")}</th>
              <th>{t("field.color")}</th>
              <th>{t("field.size")}</th>
              <th>{t("field.qty")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {grouped.map((g) => (
              <Fragment key={`group-${g.key}`}>
                <tr className="bg-[#f8f6ef]">
                  <td colSpan={9} className="py-2 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    {t("field.productionNo")}: {g.key} • {t("common.total")}: {g.items.length} {t("field.bundleNo")} • {t("field.qty")}: {g.totalQty}
                  </td>
                </tr>
                {g.items.map((b) => (
                  <tr key={b.id}>
                    <td className="font-medium">{b.bundle_no}</td>
                    <td>{b.production_no || b.production_order_id}</td>
                    <td><code>{b.barcode}</code></td>
                    <td>{b.model_id}</td>
                    <td>{b.color}</td>
                    <td>{b.size}</td>
                    <td>{b.quantity}</td>
                    <td><span className="badge">{b.status}</span></td>
                    <td className="flex gap-2">
                      <Link className="text-brand-600 hover:underline" href={`/bundles/${b.id}`}>{t("btn.view")}</Link>
                      <button type="button" className="text-slate-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${b.id}/label`)}>{t("btn.label")}</button>
                    </td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
