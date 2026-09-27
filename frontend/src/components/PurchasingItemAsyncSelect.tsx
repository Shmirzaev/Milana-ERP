"use client";

import { useEffect, useMemo, useState } from "react";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

export type PurchasingItem = { id: number; sku: string; name: string; unit: string; image_url?: string | null };

const PAGE_SIZE = 50;

export default function PurchasingItemAsyncSelect({
  value,
  selectedItem,
  onChange,
  inputId,
}: {
  value: number;
  selectedItem: PurchasingItem | null;
  onChange: (item: PurchasingItem | null) => void;
  inputId: string;
}) {
  const { t } = useT();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);

  const materials = useSWRInfinite<PurchasingItem[]>(
    (index, previous) => previous && previous.length < PAGE_SIZE ? null
      : `/api/inventory/items?group=materials&page=${index + 1}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(query)}`,
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const accessories = useSWRInfinite<PurchasingItem[]>(
    (index, previous) => previous && previous.length < PAGE_SIZE ? null
      : `/api/inventory/items?group=accessories&page=${index + 1}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(query)}`,
    fetcher,
    { persistSize: false, revalidateFirstPage: false },
  );
  const options = useMemo(() => {
    const byId = new Map<number, PurchasingItem>();
    if (selectedItem?.id === value) byId.set(value, selectedItem);
    for (const page of [...(materials.data || []), ...(accessories.data || [])]) {
      for (const item of page) byId.set(item.id, item);
    }
    return [
      { value: 0, label: t("page.purchasing.selectItem") },
      ...Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name)).map((item) => ({
        value: item.id,
        label: item.name,
        searchText: item.sku,
        imageUrl: item.image_url,
      })),
    ];
  }, [accessories.data, materials.data, selectedItem, t, value]);
  const itemById = useMemo(() => {
    const byId = new Map<number, PurchasingItem>();
    if (selectedItem?.id === value) byId.set(value, selectedItem);
    for (const page of [...(materials.data || []), ...(accessories.data || [])]) {
      for (const item of page) byId.set(item.id, item);
    }
    return byId;
  }, [accessories.data, materials.data, selectedItem, value]);
  const moreMaterials = materials.data?.at(-1)?.length === PAGE_SIZE;
  const moreAccessories = accessories.data?.at(-1)?.length === PAGE_SIZE;

  return <SearchableSelect
    inputId={inputId}
    value={value}
    options={options}
    onChange={(itemId) => onChange(Number(itemId) ? itemById.get(Number(itemId)) || null : null)}
    placeholder={t("page.purchasing.selectItem")}
    noResultsText={t("page.search.noMatches")}
    loadingText={t("common.loading")}
    loadMoreText={t("common.loadMore")}
    loading={materials.isLoading || materials.isValidating || accessories.isLoading || accessories.isValidating}
    hasMore={moreMaterials || moreAccessories}
    onSearchChange={setSearch}
    onLoadMore={() => {
      if (moreMaterials) void materials.setSize(materials.size + 1);
      if (moreAccessories) void accessories.setSize(accessories.size + 1);
    }}
    serverFilter
    required
  />;
}
