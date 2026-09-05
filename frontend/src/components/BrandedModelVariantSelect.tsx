"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import SearchableSelect from "@/components/SearchableSelect";
import VerticalModelPhoto from "@/components/VerticalModelPhoto";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { modelCodeParts } from "@/lib/modelCode";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";

type Variant = { id: number; variant_no: string; code: string; fabric?: string; picture_url?: string; status: string };
type ModelGroup = {
  id: number;
  group_key: string;
  group_model_no: string;
  group_name: string;
  primary_image_url?: string;
  status: string;
  variants: Variant[];
};
type GroupPage = { rows: ModelGroup[]; has_more: boolean };

export default function BrandedModelVariantSelect({ value, onChange }: {
  value: number;
  onChange: (id: number) => void;
}) {
  const { t } = useT();
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [chosenGroup, setChosenGroup] = useState<ModelGroup | null>(null);
  // Restore a model selected through the forecasting link when opening the dialog.
  const { data: initialModel } = useSWR(value && !chosenGroup ? `/api/models/${value}` : null, fetcher);
  const initialModelNo = initialModel ? modelCodeParts(initialModel).modelNo : "";
  const { data: initialGroups } = useSWR<GroupPage>(initialModelNo && !chosenGroup
    ? `/api/models/variant-groups?compact=true&include_total=true&status=approved&code=${encodeURIComponent(initialModelNo)}&page_size=100`
    : null, fetcher);
  const group = chosenGroup || initialGroups?.rows.find((row) => row.id === value || row.variants.some((variant) => variant.id === value));

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 180);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, error, isLoading, isValidating, size, setSize } = useSWRInfinite<GroupPage>(
    (index, previous: GroupPage | null) => previous && !previous.has_more ? null
      : `/api/models/variant-groups?compact=true&include_total=true&status=approved&page_size=30&page=${index + 1}&code=${encodeURIComponent(query)}`,
    fetcher,
    { revalidateFirstPage: false, persistSize: false },
  );
  const groups = useMemo(() => {
    const rows = new Map<string, ModelGroup>();
    if (group) rows.set(group.group_key, group);
    for (const page of data || []) for (const row of page.rows) rows.set(row.group_key, row);
    return Array.from(rows.values());
  }, [data, group]);
  const variants = (group?.variants || []).filter((variant) => variant.status === "approved");
  const selectedVariant = variants.find((variant) => variant.id === value);
  const modelLabel = group ? [group.group_model_no, group.group_name].filter(Boolean).join(" - ") : "";

  function preview(url: string | undefined, label: string) {
    const src = storageThumbnailUrl(url, 320);
    return src ? (
      <a href={imagePreviewHref(url, label)} target="_blank" rel="noreferrer" className="mt-3 block w-28" title={label}>
        <VerticalModelPhoto src={src} alt={label} />
      </a>
    ) : <p className="mt-3 text-sm text-[#8a8472]">{t("page.workOrder.noImage")}</p>;
  }

  return (
    <div className="mb-4 grid grid-cols-1 gap-4 border-b border-[#ecebe3] pb-4 sm:grid-cols-2">
      <div>
        <label className="label" htmlFor="branded-model-number">{t("page.planning.modelNumber")}</label>
        <SearchableSelect
          inputId="branded-model-number"
          value={group?.group_key || null}
          options={groups.map((row) => ({ value: row.group_key, label: [row.group_model_no, row.group_name].filter(Boolean).join(" - "), imageUrl: row.primary_image_url }))}
          onChange={(key) => {
            const next = groups.find((row) => row.group_key === key);
            if (!next || next.group_key === group?.group_key) return;
            setChosenGroup(next);
            // Families without variants remain selectable, as in the previous approved-model selector.
            onChange(next.variants.length === 0 && next.status === "approved" ? next.id : 0);
          }}
          placeholder={t("page.planning.searchModelNumber")}
          noResultsText={t("page.search.noMatches")}
          serverFilter
          onSearchChange={setSearch}
          loading={isLoading || isValidating}
          loadingText={t("common.loading")}
          hasMore={Boolean(data?.[data.length - 1]?.has_more)}
          onLoadMore={() => void setSize(size + 1)}
          loadMoreText={t("common.loadMore")}
          required
        />
        {preview(group?.primary_image_url, modelLabel || t("field.model"))}
        {error ? <p role="alert" className="mt-2 text-sm text-red-700">{t("page.planning.modelLoadFailed")}</p> : null}
      </div>
      <div>
        <label className="label" htmlFor="branded-variant-number">{t("page.planning.variantNumber")}</label>
        <SearchableSelect
          inputId="branded-variant-number"
          value={selectedVariant?.id || null}
          options={variants.map((variant) => ({ value: variant.id, label: [variant.variant_no || variant.code, variant.fabric].filter(Boolean).join(" - "), searchText: variant.variant_no || variant.code, imageUrl: variant.picture_url }))}
          onChange={(id) => onChange(Number(id))}
          placeholder={t(group ? "page.planning.selectVariant" : "newso.selectModel")}
          noResultsText={t("page.planning.noApprovedVariants")}
          disabled={!group || !variants.length}
          required={Boolean(group?.variants.length)}
        />
        {preview(selectedVariant?.picture_url, selectedVariant?.variant_no || t("page.planning.variantNumber"))}
      </div>
    </div>
  );
}
