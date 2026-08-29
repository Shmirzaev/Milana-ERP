"use client";

import { useMemo } from "react";
import SearchableSelect from "@/components/SearchableSelect";
import { useModelOptions, type ModelOption } from "@/lib/useModelOptions";

export default function ModelAsyncSelect({
  value,
  onChange,
  status,
  placeholder,
  noResultsText,
  loadingText,
  loadMoreText,
  inputId,
  disabled = false,
  required = false,
  endpoint,
}: {
  value: number | null | undefined;
  onChange: (modelId: number, option: ModelOption) => void;
  status?: string;
  placeholder: string;
  noResultsText: string;
  loadingText: string;
  loadMoreText: string;
  inputId?: string;
  disabled?: boolean;
  required?: boolean;
  endpoint?: string;
}) {
  const { options, isLoading, isLoadingMore, hasMore, setSearch, loadMore } = useModelOptions({
    selectedId: value,
    status,
    endpoint,
  });
  const optionById = useMemo(
    () => new Map(options.map((option) => [Number(option.id), option])),
    [options],
  );
  const selectOptions = useMemo(
    () => options.map((option) => ({
      value: Number(option.id),
      label: [option.code, option.name].filter(Boolean).join(" - "),
      searchText: `${option.code} ${option.name}`,
      imageUrl: option.thumbnail_url,
    })),
    [options],
  );

  return (
    <SearchableSelect
      inputId={inputId}
      value={value}
      options={selectOptions}
      onChange={(modelId) => {
        const model = optionById.get(Number(modelId));
        if (model) onChange(Number(modelId), model);
      }}
      placeholder={placeholder}
      noResultsText={noResultsText}
      loadingText={loadingText}
      loadMoreText={loadMoreText}
      loading={isLoading || isLoadingMore}
      hasMore={hasMore}
      onSearchChange={setSearch}
      onLoadMore={loadMore}
      serverFilter
      disabled={disabled}
      required={required}
    />
  );
}
