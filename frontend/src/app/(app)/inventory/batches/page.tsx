"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function BatchesPage() {
  const { t } = useT();
  const { data } = useSWR<any[]>("/api/inventory/batches", fetcher);
  return (
    <div>
      <PageHeader title={t("page.batches.title")} subtitle={t("page.batches.subtitle")} />
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.batch")}</th>
              <th>{t("field.item")}</th>
              <th>{t("field.color")}</th>
              <th>{t("field.qty")}</th>
              <th>{t("field.unit")}</th>
              <th>{t("field.cost")}</th>
              <th>{t("field.qc")}</th>
              <th>{t("field.warehouse")}</th>
              <th>{t("field.received")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((b) => (
              <tr key={b.id}>
                <td>{b.batch_no}</td><td>{b.item_id}</td><td>{b.color}</td>
                <td>{Number(b.quantity).toFixed(2)}</td><td>{b.unit}</td>
                <td>${Number(b.cost_per_unit).toFixed(2)}</td>
                <td><span className="badge">{t(`qc.${b.qc_status}`)}</span></td>
                <td>{b.warehouse_id}</td>
                <td>{new Date(b.received_date).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
