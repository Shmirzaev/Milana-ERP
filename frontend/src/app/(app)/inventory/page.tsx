"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, X } from "lucide-react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { useT } from "@/lib/i18n";

type InventoryGroup = "materials" | "accessories";

const GROUPS: { value: InventoryGroup; titleKey: string; subtitleKey: string }[] = [
  { value: "materials", titleKey: "page.inventory.materialTitle", subtitleKey: "page.inventory.materialSubtitle" },
  { value: "accessories", titleKey: "page.inventory.accessoryTitle", subtitleKey: "page.inventory.accessorySubtitle" },
];

export default function InventoryPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const q = (searchParams.get("q") ?? "").trim();
  const group: InventoryGroup = searchParams.get("group") === "accessories" ? "accessories" : "materials";
  const selectedGroup = GROUPS.find((g) => g.value === group) ?? GROUPS[0];
  const { t } = useT();
  const [searchDraft, setSearchDraft] = useState(q);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const stockUrl = `/api/inventory/stock?group=${group}&include_total=true&page=${page}&page_size=${pageSize}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  const { data: stockPage } = useSWR<any>(stockUrl, fetcher);
  const stock = useMemo<any[]>(() => stockPage?.rows || [], [stockPage]);
  const { data: items } = useSWR<any[]>(`/api/inventory/items?group=${group}`, fetcher);
  const activeSearch = searchDraft.trim().toLowerCase();
  const rows = useMemo(() => {
    if (!activeSearch) return stock;
    return stock.filter((s) => {
      const sku = String(s.item_sku ?? "").toLowerCase();
      const name = String(s.item_name ?? "").toLowerCase();
      const unit = String(s.unit ?? "").toLowerCase();
      return sku.includes(activeSearch) || name.includes(activeSearch) || unit.includes(activeSearch);
    });
  }, [activeSearch, stock]);
  const searchApplied = activeSearch === q.toLowerCase();
  const totalLines = activeSearch
    ? (searchApplied ? Number(stockPage?.total || rows.length) : rows.length)
    : Number(stockPage?.total || 0);

  useEffect(() => {
    setPage(1);
  }, [group, q]);

  useEffect(() => {
    setSearchDraft(q);
  }, [q]);

  function inventoryHref(nextGroup: InventoryGroup, query = q) {
    const params = new URLSearchParams();
    if (nextGroup === "accessories") params.set("group", "accessories");
    const trimmed = query.trim();
    if (trimmed) params.set("q", trimmed);
    const qs = params.toString();
    return `/inventory${qs ? `?${qs}` : ""}`;
  }

  function applySearch() {
    router.push(inventoryHref(group, searchDraft));
    setPage(1);
  }

  function submitSearch(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    applySearch();
  }

  function clearSearch() {
    setSearchDraft("");
    router.push(inventoryHref(group, ""));
    setPage(1);
  }

  return (
    <div>
      <PageHeader title={t(selectedGroup.titleKey)} subtitle={t(selectedGroup.subtitleKey)} />
      <div className="mb-4 flex flex-wrap gap-2">
        {GROUPS.map((option) => {
          const active = option.value === group;
          return (
            <Link
              key={option.value}
              href={inventoryHref(option.value)}
              className={`rounded-md border px-3 py-2 text-sm font-medium transition ${
                active
                  ? "border-[#14110b] bg-[#14110b] text-[#fdfcf8]"
                  : "border-[#ded8c8] bg-[#fdfcf8] text-[#56503f] hover:border-[#bcb39f] hover:text-[#14110b]"
              }`}
            >
              {t(option.titleKey)}
            </Link>
          );
        })}
      </div>
      <form onSubmit={submitSearch} className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3">
          <Search className="h-4 w-4 shrink-0 text-[#8a8472]" />
          <input
            className="w-full min-w-0 bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
            placeholder={t("page.inventory.searchPlaceholder")}
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
          />
          {q ? (
            <button type="button" className="icon-btn" onClick={clearSearch} title={t("common.clear")}>
              <X />
            </button>
          ) : null}
        </div>
        <button type="button" className="btn btn-primary sm:w-auto" onClick={applySearch}>
          <Search />
          {t("common.search")}
        </button>
      </form>
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 lg:gap-4">
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.itemTypes")}</div><div className="text-2xl font-semibold">{items?.length ?? 0}</div></div>
        <div className="card p-4"><div className="text-xs text-slate-500">{t("page.inventory.linesTracked")}</div><div className="text-2xl font-semibold">{totalLines}</div></div>
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
          <tbody>{rows.map((s) => <tr key={s.item_id}><td>{s.item_sku}</td><td>{s.item_name}</td><td>{Number(s.quantity).toFixed(2)}</td><td>{s.unit}</td></tr>)}</tbody>
        </table>
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={totalLines || rows.length}
          count={rows.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </div>
    </div>
  );
}
