"use client";

import { type FormEvent, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Search, X } from "lucide-react";
import useSWR from "swr";
import ImageThumbnail from "@/components/ImageThumbnail";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

type ArchivedBatch = {
  id: number;
  item_name?: string | null;
  item_sku?: string | null;
  item_image_url?: string | null;
  batch_no: string;
  internal_batch_no?: string | null;
  supplier_name?: string | null;
  warehouse_name?: string | null;
  color?: string | null;
  order_no?: string | null;
  image_url?: string | null;
  received_date?: string | null;
  archived_at?: string | null;
  archive_reason?: "deleted" | "used" | null;
  received_quantity?: number;
  used_quantity?: number;
  quantity: number;
  unit: string;
};

type ArchivedBatchPage = {
  rows: ArchivedBatch[];
  total: number;
  page: number;
  page_size: number;
};

type Supplier = { id: number; name: string };

function formatQuantity(value: number | null | undefined) {
  const quantity = Number(value || 0);
  return Number.isFinite(quantity) ? quantity.toFixed(2) : "0.00";
}

function formatDate(value: string | null | undefined, lang: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const locale = lang === "ru" ? "ru-RU" : lang === "uz" ? "uz-UZ" : "en-GB";
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export default function FabricInventoryArchivePage() {
  const { t, lang } = useT();
  const [searchDraft, setSearchDraft] = useState("");
  const [query, setQuery] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [supplierId, setSupplierId] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  const archiveUrl = useMemo(() => {
    const params = new URLSearchParams({
      group: "materials",
      archived: "true",
      include_total: "true",
      page: String(page),
      page_size: String(pageSize),
    });
    if (query) params.set("q", query);
    if (createdFrom) params.set("created_from", createdFrom);
    if (createdTo) params.set("created_to", createdTo);
    if (supplierId) params.set("supplier_id", String(supplierId));
    return `/api/inventory/batches?${params.toString()}`;
  }, [createdFrom, createdTo, page, pageSize, query, supplierId]);

  const { data, error, isLoading } = useSWR<ArchivedBatchPage>(archiveUrl, fetcher);
  const { data: suppliers } = useSWR<Supplier[]>("/api/suppliers", fetcher);
  const rows = data?.rows || [];

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setQuery(searchDraft.trim());
    setPage(1);
  }

  function clearSearch() {
    setSearchDraft("");
    setQuery("");
    setPage(1);
  }

  function reasonLabel(batch: ArchivedBatch) {
    return batch.archive_reason === "deleted"
      ? t("page.inventory.archiveReasonDeleted")
      : t("page.inventory.archiveReasonUsed");
  }

  return (
    <div>
      <PageHeader
        title={t("page.inventory.archiveTitle")}
        subtitle={t("page.inventory.archiveSubtitle")}
        actions={(
          <Link href="/inventory?group=materials" className="btn">
            <ArrowLeft />
            {t("page.inventory.backToInventory")}
          </Link>
        )}
      />

      <form onSubmit={submitSearch} className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3">
          <Search className="h-4 w-4 shrink-0 text-[#8a8472]" />
          <input
            className="w-full min-w-0 bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
            placeholder={t("page.inventory.searchPlaceholder")}
            value={searchDraft}
            onChange={(event) => setSearchDraft(event.target.value)}
          />
          {query ? (
            <button type="button" className="icon-btn" onClick={clearSearch} title={t("common.clear")}>
              <X />
            </button>
          ) : null}
        </div>
        <button type="submit" className="btn btn-primary sm:w-auto">
          <Search />
          {t("common.search")}
        </button>
      </form>

      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3 lg:w-[900px]">
        <label className="block">
          <span className="label">{t("common.createdFrom")}</span>
          <input
            className="input"
            type="date"
            value={createdFrom}
            onChange={(event) => { setCreatedFrom(event.target.value); setPage(1); }}
          />
        </label>
        <label className="block">
          <span className="label">{t("common.createdTo")}</span>
          <input
            className="input"
            type="date"
            value={createdTo}
            onChange={(event) => { setCreatedTo(event.target.value); setPage(1); }}
          />
        </label>
        <label className="block">
          <span className="label">{t("field.supplier")}</span>
          <select
            className="input"
            value={supplierId || ""}
            onChange={(event) => { setSupplierId(Number(event.target.value) || 0); setPage(1); }}
          >
            <option value="">-</option>
            {(suppliers || []).map((supplier) => (
              <option key={supplier.id} value={supplier.id}>{supplier.name}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="card overflow-hidden">
        {isLoading ? <div className="p-4 text-sm text-[#8a8472]">{t("common.loading")}</div> : null}
        {error ? <div className="p-4 text-sm text-red-700">{t("page.inventory.archiveLoadFailed")}</div> : null}
        {!isLoading && !error && rows.length === 0 ? (
          <div className="p-4 text-sm text-[#8a8472]">{t("page.inventory.emptyArchive")}</div>
        ) : null}

        {rows.length > 0 ? (
          <>
            <div className="divide-y divide-[#ecebe3] md:hidden">
              {rows.map((batch) => (
                <article key={batch.id} className="flex gap-3 p-4">
                  <ImageThumbnail
                    imageUrl={batch.image_url || batch.item_image_url}
                    label={batch.item_name || batch.batch_no}
                    title={t("field.picture")}
                    emptyLabel="-"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <div className="font-medium text-[#14110b]">{batch.item_name || "-"}</div>
                        <div className="mt-1 text-xs text-[#6f684f]">
                          {t("field.batch")}: <span className="mono text-[#14110b]">{batch.batch_no}</span>
                        </div>
                      </div>
                      <span className="rounded-md border border-[#d8d1c0] bg-[#f4f1e8] px-2 py-1 text-xs text-[#56503f]">
                        {reasonLabel(batch)}
                      </span>
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                      <div><div className="label mb-0">{t("page.inventory.receivedQuantity")}</div><div className="mono">{formatQuantity(batch.received_quantity)} {batch.unit}</div></div>
                      <div><div className="label mb-0">{t("page.inventory.usedQuantity")}</div><div className="mono">{formatQuantity(batch.used_quantity)} {batch.unit}</div></div>
                      <div><div className="label mb-0">{t("field.supplier")}</div><div>{batch.supplier_name || "-"}</div></div>
                      <div><div className="label mb-0">{t("page.inventory.archivedAt")}</div><div>{formatDate(batch.archived_at, lang)}</div></div>
                    </div>
                  </div>
                </article>
              ))}
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="table min-w-[1120px]">
                <thead>
                  <tr>
                    <th>{t("field.picture")}</th>
                    <th>{t("field.batch")}</th>
                    <th>{t("common.name")}</th>
                    <th>{t("field.supplier")} / {t("field.warehouse")}</th>
                    <th>{t("page.inventory.receivedQuantity")}</th>
                    <th>{t("page.inventory.usedQuantity")}</th>
                    <th>{t("page.inventory.archiveReason")}</th>
                    <th>{t("page.inventory.archivedAt")}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((batch) => (
                    <tr key={batch.id}>
                      <td>
                        <ImageThumbnail
                          imageUrl={batch.image_url || batch.item_image_url}
                          label={batch.item_name || batch.batch_no}
                          title={t("field.picture")}
                          emptyLabel="-"
                        />
                      </td>
                      <td>
                        <div className="mono font-semibold text-[#14110b]">{batch.batch_no}</div>
                        {batch.internal_batch_no ? <div className="mt-1 text-xs text-[#6f684f]">{batch.internal_batch_no}</div> : null}
                      </td>
                      <td>
                        <div className="font-medium text-[#14110b]">{batch.item_name || "-"}</div>
                        <div className="mt-1 text-xs text-[#6f684f]">{[batch.item_sku, batch.color, batch.order_no].filter(Boolean).join(" · ") || "-"}</div>
                      </td>
                      <td>
                        <div>{batch.supplier_name || "-"}</div>
                        <div className="mt-1 text-xs text-[#6f684f]">{batch.warehouse_name || "-"}</div>
                      </td>
                      <td className="mono">{formatQuantity(batch.received_quantity)} {batch.unit}</td>
                      <td className="mono">{formatQuantity(batch.used_quantity)} {batch.unit}</td>
                      <td><span className="rounded-md border border-[#d8d1c0] bg-[#f4f1e8] px-2 py-1 text-xs text-[#56503f]">{reasonLabel(batch)}</span></td>
                      <td>
                        <div>{formatDate(batch.archived_at, lang)}</div>
                        <div className="mt-1 text-xs text-[#6f684f]">{formatDate(batch.received_date, lang)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}

        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={Number(data?.total || 0)}
          count={rows.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </div>
    </div>
  );
}
