"use client";

import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { RefreshCw } from "lucide-react";
import DepartmentOrderList, { type DepartmentOrder } from "@/components/DepartmentOrderList";
import PageHeader from "@/components/PageHeader";
import { packagingDepartmentForSession } from "@/lib/access";
import { fetcher } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { formatVariantNumber } from "@/lib/variantDisplay";

export default function PartiallyPackagedOrdersPage() {
  const { t } = useT();
  const { me } = useMe();
  const params = useSearchParams();
  const department = packagingDepartmentForSession(me, params.get("packaging_department"));
  const factory = department === "BPK" ? "factory.besttex" : department === "ECP" ? "factory.ecoCotton" : "factory.milana";
  const { data, error, isLoading, mutate } = useSWR<{ partially_packaged: DepartmentOrder[] }>(
    me ? `/api/inbox?dept=${department}` : null, fetcher, { refreshInterval: 10_000 },
  );
  const [query, setQuery] = useState("");
  const rows = useMemo(() => {
    const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return (data?.partially_packaged || []).filter((row) => {
      const text = [row.order_no, row.production_no, row.sales_order_no, row.planning_order_no,
        row.planning_order_name, row.model_no, row.model_name, row.variant_no,
        formatVariantNumber(row.variant_no), row.material_item_sku, row.material_item_name, row.size_summary]
        .filter(Boolean).join(" ").toLocaleLowerCase();
      return words.every((word) => text.includes(word));
    });
  }, [data, query]);

  return (
    <div>
      <PageHeader title={t("floor.partiallyPackaged")} subtitle={t(factory)} actions={(
        <button type="button" className="btn" onClick={() => void mutate()}>
          <RefreshCw className="h-4 w-4" aria-hidden="true" />{t("btn.refresh")}
        </button>
      )} />
      <input type="search" className="input mb-4 w-full sm:max-w-md" aria-label={t("common.search")}
        placeholder={t("common.search")} value={query} onChange={(event) => setQuery(event.target.value)} />
      {error ? <div role="alert" className="card p-4 text-red-700">{error.message}</div>
        : isLoading || !me ? <div className="card p-4">{t("common.loading")}</div>
          : <DepartmentOrderList rows={rows} title={t("page.deptInbox.orders", { count: rows.length })}
              emptyLabel={t("floor.noPartialOrders")} partialPackaging t={t} />}
    </div>
  );
}
