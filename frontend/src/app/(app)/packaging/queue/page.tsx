"use client";

import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";
import { ArrowRight, PackageOpen, RefreshCw, Search } from "lucide-react";
import useSWR from "swr";

import PageHeader from "@/components/PageHeader";
import { fetcher } from "@/lib/api";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";
import { useT } from "@/lib/i18n";
import { storageThumbnailUrl } from "@/lib/modelImages";

type ReceivedOrder = {
  work_order_id: number;
  production_order_id: number;
  production_no?: string | null;
  order_no?: string | null;
  model_code?: string | null;
  model_name?: string | null;
  variant_no?: string | null;
  model_image_url?: string | null;
  received_quantity: number;
  packed_quantity: number;
  remaining_quantity: number;
  waiting_replacement_quantity: number;
  last_received_at: string;
};

function orderLabel(row: ReceivedOrder) {
  return row.order_no || row.production_no || `#${row.production_order_id}`;
}

export default function PackagingQueuePage() {
  const { t } = useT();
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const queueUrl = useMemo(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (search) params.set("q", search);
    return `/api/packaging/received-orders?${params.toString()}`;
  }, [search]);
  const { data: orders = [], mutate, isLoading } = useSWR<ReceivedOrder[]>(
    queueUrl,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchDraft.trim());
  }

  return (
    <div>
      <PageHeader
        title={t("page.packagingReceive.queueTitle")}
        subtitle={t("page.packagingReceive.queueHint")}
        actions={(
          <button type="button" className="btn" onClick={() => mutate()}>
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            {t("btn.refresh")}
          </button>
        )}
      />

      <section className="card p-4">
        <form className="mb-4 flex w-full gap-2 md:max-w-md" onSubmit={submitSearch}>
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
            <input
              className="input pl-9"
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder={t("page.packagingReceive.queueSearch")}
            />
          </div>
          <button type="submit" className="btn">{t("common.search")}</button>
        </form>

        <div className="overflow-x-auto">
          <table className="table min-w-[960px]">
            <thead>
              <tr>
                <th className="w-20">{t("field.picture")}</th>
                <th>{t("field.orderNo")}</th>
                <th>{t("page.packagingReceive.modelVariant")}</th>
                <th className="text-right">{t("field.received")}</th>
                <th className="text-right">{t("page.packagingReceive.packed")}</th>
                <th className="text-right">{t("page.packagingReceive.readyToPack")}</th>
                <th className="text-right">{t("replacement.waiting")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((row) => (
                <tr key={row.work_order_id}>
                  <td>
                    <div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded-md border border-[#e3dfd3] bg-[#f7f5ef]">
                      {row.model_image_url ? (
                        <img
                          src={storageThumbnailUrl(row.model_image_url, 160)}
                          alt={[row.model_code, row.model_name].filter(Boolean).join(" - ")}
                          className="h-full w-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <PackageOpen className="h-5 w-5 text-[#8a8472]" aria-hidden="true" />
                      )}
                    </div>
                  </td>
                  <td>
                    <div className="font-medium text-[#14110b]">{orderLabel(row)}</div>
                    <div className="text-xs text-[#8a8472]">{new Date(row.last_received_at).toLocaleString()}</div>
                  </td>
                  <td>
                    <div className="font-medium text-[#14110b]">{row.model_name || row.model_code || "-"}</div>
                    <div className="text-xs text-[#8a8472]">
                      {[row.model_code, row.variant_no && row.variant_no !== row.model_code ? row.variant_no : null]
                        .filter(Boolean)
                        .join(" · ") || "-"}
                    </div>
                  </td>
                  <td className="text-right tabular-nums">{row.received_quantity.toLocaleString()}</td>
                  <td className="text-right tabular-nums">{row.packed_quantity.toLocaleString()}</td>
                  <td className="text-right font-semibold tabular-nums text-[#14110b]">{row.remaining_quantity.toLocaleString()}</td>
                  <td className="text-right font-semibold tabular-nums text-amber-800">
                    {Number(row.waiting_replacement_quantity || 0).toLocaleString()}
                  </td>
                  <td>
                    <Link href={`/work-orders/${row.work_order_id}/packaging`} className="btn btn-primary whitespace-nowrap">
                      {t("page.packagingReceive.packing")}
                      <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    </Link>
                  </td>
                </tr>
              ))}
              {!isLoading && orders.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-sm text-[#8a8472]">{t("page.packagingReceive.queueEmpty")}</td>
                </tr>
              )}
              {isLoading && orders.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-sm text-[#8a8472]">{t("common.loading")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
