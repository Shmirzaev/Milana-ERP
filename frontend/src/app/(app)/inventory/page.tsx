"use client";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function InventoryPage() {
  const { t } = useT();
  const { data: stock } = useSWR<any[]>("/api/inventory/stock", fetcher);
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);
  return (
    <div>
      <PageHeader title={t("page.inventory.title")} subtitle={t("page.inventory.subtitle")} />
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.itemTypes")}</div><div className="text-2xl font-semibold">{items?.length ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.linesTracked")}</div><div className="text-2xl font-semibold">{stock?.length ?? 0}</div></div>
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.sku")}</th>
              <th>{t("common.name")}</th>
              <th>{t("field.quantity")}</th>
              <th>{t("field.unit")}</th>
            </tr>
          </thead>
          <tbody>{stock?.map((s) => <tr key={s.item_id}><td>{s.item_sku}</td><td>{s.item_name}</td><td>{Number(s.quantity).toFixed(2)}</td><td>{s.unit}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
