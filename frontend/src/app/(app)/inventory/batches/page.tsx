"use client";
import { formatOrderReference } from "@/lib/orderRef";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import SearchableSelect from "@/components/SearchableSelect";
import { useT } from "@/lib/i18n";

type ItemOption = { id: number; sku: string; name: string };
type ItemPage = { rows: ItemOption[]; total: number };

export default function BatchesPage() {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [itemId, setItemId] = useState(0);
  const [selectedItem, setSelectedItem] = useState<ItemOption | null>(null);
  const [itemPickerOpen, setItemPickerOpen] = useState(false);
  const [itemSearch, setItemSearch] = useState("");
  const [itemQuery, setItemQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setItemQuery(itemSearch.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [itemSearch]);
  const [availability, setAvailability] = useState("all");
  const query = `include_total=true&page=${page}&page_size=${pageSize}${itemId ? `&item_id=${itemId}` : ""}`;
  const { data: pageData } = useSWR<any>(`/api/inventory/batches?${query}`, fetcher);
  const { data: itemPages, size: itemPageCount, setSize: setItemPageCount, isLoading: itemsLoading, isValidating: itemsValidating } = useSWRInfinite<ItemPage>(
    (index, previous) => !itemPickerOpen || (previous && index * 50 >= previous.total) ? null
      : `/api/inventory/items?page=${index + 1}&page_size=50&include_total=true&q=${encodeURIComponent(itemQuery)}`,
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const loadedItems = useMemo(() => (itemPages || []).flatMap((page) => page.rows), [itemPages]);
  const itemOptions = useMemo(() => {
    const byId = new Map<number, ItemOption>();
    if (selectedItem?.id === itemId) byId.set(itemId, selectedItem);
    for (const item of loadedItems) byId.set(item.id, item);
    return [{ value: 0, label: t("common.all") }, ...Array.from(byId.values()).map((item) => ({
      value: item.id, label: item.name, searchText: item.sku,
    }))];
  }, [itemId, loadedItems, selectedItem, t]);
  const itemsById = useMemo(() => new Map(loadedItems.map((item) => [item.id, item])), [loadedItems]);
  const data: any[] = useMemo(() => {
    const rows = pageData?.rows || [];
    if (availability === "reserved") return rows.filter((row: any) => Number(row.reserved_quantity || 0) > 0);
    if (availability === "available") return rows.filter((row: any) => Number(row.available_quantity || 0) > 0);
    return rows;
  }, [availability, pageData]);
  return (
    <div>
      <PageHeader title={t("page.batches.title")} subtitle={t("page.batches.subtitle")} />
      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
        <div>
          <label className="label">{t("field.item")}</label>
          <SearchableSelect
            value={itemId}
            options={itemOptions}
            onChange={(value, option) => {
              const nextId = Number(value);
              setSelectedItem(nextId ? itemsById.get(nextId) ?? { id: nextId, name: option.label, sku: option.searchText || "" } : null);
              setItemId(nextId);
              setPage(1);
            }}
            placeholder={t("field.item")}
            noResultsText={t("page.search.noMatches")}
            loadingText={t("common.loading")}
            loadMoreText={`${t("common.loadMore")} (${loadedItems.length} / ${itemPages?.[0]?.total ?? 0})`}
            loading={itemsLoading || itemsValidating}
            hasMore={Boolean(itemPages?.at(-1) && loadedItems.length < (itemPages?.[0]?.total ?? 0))}
            onSearchChange={setItemSearch}
            onLoadMore={() => void setItemPageCount(itemPageCount + 1)}
            onOpenChange={setItemPickerOpen}
            serverFilter
          />
        </div>
        <div>
          <label className="label">{t("field.available")}</label>
          <select className="input" value={availability} onChange={(event) => setAvailability(event.target.value)}>
            <option value="all">{t("common.all")}</option>
            <option value="reserved">{t("reservation.filterReserved")}</option>
            <option value="available">{t("reservation.filterAvailable")}</option>
          </select>
        </div>
      </div>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.batch").toUpperCase()}</th>
              <th>{t("field.materialName").toUpperCase()}</th>
              <th>{t("field.materialColor").toUpperCase()}</th>
              <th>{t("field.oldCode").toUpperCase()}</th>
              <th>{t("field.colorCode").toUpperCase()}</th>
              <th>{t("field.colorStatus").toUpperCase()}</th>
              <th>{t("field.orderNo").toUpperCase()}</th>
              <th>{t("field.netto").toUpperCase()}</th>
              <th>{t("field.reserved").toUpperCase()}</th>
              <th>{t("field.available").toUpperCase()}</th>
              <th>{t("field.pieceCount").toUpperCase()}</th>
              <th>{t("field.processes").toUpperCase()}</th>
              <th>{t("reservation.activeReservations")}</th>
              <th>{t("field.received")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((b) => (
              <tr key={b.id}>
                <td>{b.batch_no}</td>
                <td>{b.item_name || b.item_id}</td>
                <td>{b.color || "-"}</td>
                <td>{b.old_code || "-"}</td>
                <td>{b.color_code || "-"}</td>
                <td>{b.color_status || "-"}</td>
                <td>{formatOrderReference(b.order_no || "-")}</td>
                <td>{Number(b.quantity).toFixed(2)}</td>
                <td>{Number(b.reserved_quantity || 0).toFixed(2)}</td>
                <td>{Number(b.available_quantity ?? b.quantity).toFixed(2)}</td>
                <td>{b.piece_count ?? "-"}</td>
                <td>{b.processes || "-"}</td>
                <td>
                  {(b.active_reservations || []).length ? (
                    <div className="space-y-1">
                      {b.active_reservations.map((reservation: any) => (
                        <Link
                          key={reservation.id}
                          href={`/production-orders/${reservation.production_order_id}`}
                          className="block text-xs text-brand-600 hover:underline"
                        >
                          {reservation.reservation_no} - {Number(reservation.remaining_quantity || 0).toFixed(2)} {reservation.unit}
                        </Link>
                      ))}
                    </div>
                  ) : "-"}
                </td>
                <td>{new Date(b.received_date).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={availability === "all" ? Number(pageData?.total || data.length) : data.length}
          count={data.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </div>
    </div>
  );
}
