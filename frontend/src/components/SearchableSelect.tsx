"use client";

import { createPortal } from "react-dom";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, ImageIcon, Search } from "lucide-react";
import { normalizeModelSearch } from "@/lib/modelCode";
import { storageThumbnailUrl } from "@/lib/modelImages";

const LOCAL_RENDER_PAGE_SIZE = 80;

export type SearchableSelectOption<T extends string | number = string | number> = {
  value: T;
  label: string;
  searchText?: string;
  imageUrl?: string | null;
  metaText?: string;
  tone?: "default" | "success";
};

export default function SearchableSelect<T extends string | number>({
  value,
  options,
  onChange,
  placeholder,
  noResultsText,
  disabled = false,
  required = false,
  inputId,
  serverFilter = false,
  loading = false,
  hasMore = false,
  loadingText = "Loading...",
  loadMoreText = "Load more",
  onSearchChange,
  onLoadMore,
}: {
  value: T | null | undefined;
  options: SearchableSelectOption<T>[];
  onChange: (value: T, option: SearchableSelectOption<T>) => void;
  placeholder: string;
  noResultsText: string;
  disabled?: boolean;
  required?: boolean;
  inputId?: string;
  serverFilter?: boolean;
  loading?: boolean;
  hasMore?: boolean;
  loadingText?: string;
  loadMoreText?: string;
  onSearchChange?: (query: string) => void;
  onLoadMore?: () => void;
}) {
  const generatedId = useId();
  const id = inputId || `searchable-select-${generatedId}`;
  const listboxId = `${id}-listbox`;
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listboxRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [localRenderLimit, setLocalRenderLimit] = useState(LOCAL_RENDER_PAGE_SIZE);
  const [listboxPosition, setListboxPosition] = useState<{
    left: number;
    top: number;
    width: number;
    maxHeight: number;
    transform?: string;
  } | null>(null);
  const activeOptionId = `${listboxId}-option-${activeIndex}`;

  const selectedOption = useMemo(
    () => options.find((option) => String(option.value) === String(value ?? "")) || null,
    [options, value],
  );

  const searchableOptions = useMemo(
    () => options.map((option) => ({
      option,
      searchKey: normalizeModelSearch(`${option.label} ${option.searchText || ""}`),
    })),
    [options],
  );

  useEffect(() => {
    if (!open) setQuery(selectedOption?.label || "");
  }, [open, selectedOption]);

  const filteredOptions = useMemo(() => {
    if (serverFilter) return options;
    const needle = normalizeModelSearch(query);
    if (!needle || query === selectedOption?.label) return options;
    return searchableOptions
      .filter(({ searchKey }) => searchKey.includes(needle))
      .map(({ option }) => option);
  }, [options, query, searchableOptions, selectedOption?.label, serverFilter]);

  const visibleOptions = useMemo(() => {
    if (serverFilter || filteredOptions.length <= localRenderLimit) return filteredOptions;
    const visible = filteredOptions.slice(0, localRenderLimit);
    if (
      query === selectedOption?.label
      && selectedOption
      && !visible.some((option) => String(option.value) === String(selectedOption.value))
    ) {
      return [selectedOption, ...visible.slice(0, Math.max(0, localRenderLimit - 1))];
    }
    return visible;
  }, [filteredOptions, localRenderLimit, query, selectedOption, serverFilter]);
  const hasMoreLocalOptions = !serverFilter && visibleOptions.length < filteredOptions.length;
  const canLoadMore = hasMoreLocalOptions || hasMore;

  const loadMoreOptions = useCallback(() => {
    if (hasMoreLocalOptions) {
      setLocalRenderLimit((current) => Math.min(current + LOCAL_RENDER_PAGE_SIZE, filteredOptions.length));
      return;
    }
    onLoadMore?.();
  }, [filteredOptions.length, hasMoreLocalOptions, onLoadMore]);

  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(0, visibleOptions.length - 1)));
  }, [visibleOptions.length]);

  useEffect(() => {
    if (open) document.getElementById(activeOptionId)?.scrollIntoView({ block: "nearest" });
  }, [activeOptionId, open]);

  useEffect(() => {
    function closeOnOutsideClick(event: MouseEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !listboxRef.current?.contains(target)) setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, []);

  const updateListboxPosition = useCallback(() => {
    const root = rootRef.current;
    if (!root) return;

    const rect = root.getBoundingClientRect();
    const viewport = window.visualViewport;
    const viewportLeft = viewport?.offsetLeft ?? 0;
    const viewportTop = viewport?.offsetTop ?? 0;
    const viewportWidth = viewport?.width ?? window.innerWidth;
    const viewportHeight = viewport?.height ?? window.innerHeight;
    const viewportRight = viewportLeft + viewportWidth;
    const viewportBottom = viewportTop + viewportHeight;
    const gutter = 8;
    const gap = 4;
    const roomBelow = viewportBottom - rect.bottom - gap - gutter;
    const roomAbove = rect.top - viewportTop - gap - gutter;
    const openAbove = roomBelow < 192 && roomAbove > roomBelow;
    const maxHeight = Math.max(0, Math.min(256, openAbove ? roomAbove : roomBelow));
    const width = Math.max(0, Math.min(rect.width, viewportWidth - gutter * 2));
    const left = Math.max(
      viewportLeft + gutter,
      Math.min(rect.left, viewportRight - width - gutter),
    );

    setListboxPosition({
      left,
      top: openAbove ? rect.top - gap : rect.bottom + gap,
      width,
      maxHeight,
      transform: openAbove ? "translateY(-100%)" : undefined,
    });
  }, []);

  useEffect(() => {
    if (!open) {
      setListboxPosition(null);
      return;
    }

    updateListboxPosition();
    const viewport = window.visualViewport;
    window.addEventListener("resize", updateListboxPosition);
    window.addEventListener("scroll", updateListboxPosition, true);
    viewport?.addEventListener("resize", updateListboxPosition);
    viewport?.addEventListener("scroll", updateListboxPosition);
    return () => {
      window.removeEventListener("resize", updateListboxPosition);
      window.removeEventListener("scroll", updateListboxPosition, true);
      viewport?.removeEventListener("resize", updateListboxPosition);
      viewport?.removeEventListener("scroll", updateListboxPosition);
    };
  }, [open, updateListboxPosition]);

  function choose(option: SearchableSelectOption<T>) {
    onChange(option.value, option);
    setQuery(option.label);
    setOpen(false);
    inputRef.current?.focus();
  }

  return (
    <div ref={rootRef} className="relative min-w-0">
      <div className={`input flex items-center gap-2 px-3 py-0 ${disabled ? "cursor-not-allowed bg-[#f4f2eb] opacity-70" : "bg-white"}`}>
        <Search className="h-4 w-4 shrink-0 text-[#8a8472]" aria-hidden="true" />
        <input
          ref={inputRef}
          id={id}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={open && visibleOptions.length ? activeOptionId : undefined}
          aria-required={required}
          className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none"
          value={query}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          onFocus={(event) => {
            setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE);
            setOpen(true);
            event.currentTarget.select();
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE);
            onSearchChange?.(event.target.value);
            setActiveIndex(0);
            setOpen(true);
          }}
          onBlur={() => {
            window.setTimeout(() => {
              if (!rootRef.current?.contains(document.activeElement)) setOpen(false);
            }, 0);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
              setActiveIndex((current) => Math.min(current + 1, Math.max(0, visibleOptions.length - 1)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              setActiveIndex((current) => Math.max(0, current - 1));
            } else if (event.key === "Enter" && open && visibleOptions[activeIndex]) {
              event.preventDefault();
              choose(visibleOptions[activeIndex]);
            } else if (event.key === "Escape") {
              event.preventDefault();
              setOpen(false);
              setQuery(selectedOption?.label || "");
            }
          }}
        />
        <button
          type="button"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[#6b6251] hover:bg-[#f1eee5]"
          aria-label={placeholder}
          disabled={disabled}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            const nextOpen = !open;
            if (nextOpen) setLocalRenderLimit(LOCAL_RENDER_PAGE_SIZE);
            setOpen(nextOpen);
            if (nextOpen) {
              inputRef.current?.focus();
              inputRef.current?.select();
            }
          }}
        >
          <ChevronDown className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {open && !disabled && listboxPosition && createPortal((
        <div
          ref={listboxRef}
          id={listboxId}
          role="listbox"
          className="fixed z-[100] overflow-y-auto overscroll-contain rounded-md border border-[#d8d2c2] bg-white py-1 shadow-sm"
          style={listboxPosition}
          onScroll={(event) => {
            const target = event.currentTarget;
            if (canLoadMore && !loading && target.scrollHeight - target.scrollTop - target.clientHeight < 48) {
              loadMoreOptions();
            }
          }}
        >
          {visibleOptions.map((option, index) => {
            const selected = String(option.value) === String(value ?? "");
            const showImage = Object.prototype.hasOwnProperty.call(option, "imageUrl");
            const imageUrl = storageThumbnailUrl(option.imageUrl, 128);
            const success = option.tone === "success";
            const rowClass = success
              ? index === activeIndex ? "bg-emerald-100 text-emerald-950" : "bg-emerald-50 text-emerald-950 hover:bg-emerald-100"
              : index === activeIndex ? "bg-[#f3f0e7]" : "hover:bg-[#f8f6ef]";
            return (
              <button
                type="button"
                role="option"
                id={`${listboxId}-option-${index}`}
                aria-selected={selected}
                key={String(option.value)}
                className={`flex w-full items-start gap-2 px-3 py-2 text-left text-sm ${rowClass}`}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(option)}
              >
                {showImage && (
                  imageUrl ? (
                    <img
                      src={imageUrl}
                      alt=""
                      className="h-11 w-11 shrink-0 rounded-md border border-[#ded9ca] bg-white object-cover"
                      loading="lazy"
                      decoding="async"
                      width={44}
                      height={44}
                    />
                  ) : (
                    <span
                      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-[#ded9ca] bg-[#f4f1e8] text-[#9a927f]"
                      aria-hidden="true"
                    >
                      <ImageIcon className="h-4 w-4" />
                    </span>
                  )
                )}
                <span className="min-w-0 flex-1 self-center break-words">
                  <span className="block">{option.label}</span>
                  {option.metaText ? (
                    <span className={`mt-0.5 block text-xs ${success ? "text-emerald-700" : "text-[#6f6a5b]"}`}>
                      {option.metaText}
                    </span>
                  ) : null}
                </span>
                <Check className={`h-4 w-4 shrink-0 self-center ${selected ? "text-[#14110b]" : "invisible"}`} aria-hidden="true" />
              </button>
            );
          })}
          {filteredOptions.length === 0 && !loading && (
            <div className="px-3 py-3 text-sm text-[#8a8472]">{noResultsText}</div>
          )}
          {loading && (
            <div className="px-3 py-2 text-sm text-[#8a8472]">{loadingText}</div>
          )}
          {canLoadMore && !loading && (
            <div role="presentation" className="border-t border-[#ece8dc] p-1">
              <button
                type="button"
                className="w-full rounded-md px-3 py-2 text-left text-sm font-medium text-[#56503f] hover:bg-[#f8f6ef]"
                onMouseDown={(event) => event.preventDefault()}
                onClick={loadMoreOptions}
              >
                {loadMoreText}
              </button>
            </div>
          )}
        </div>
      ), document.body)}
    </div>
  );
}
