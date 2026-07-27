"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";

export type SearchableSelectOption<T extends string | number = string | number> = {
  value: T;
  label: string;
  searchText?: string;
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
}: {
  value: T | null | undefined;
  options: SearchableSelectOption<T>[];
  onChange: (value: T, option: SearchableSelectOption<T>) => void;
  placeholder: string;
  noResultsText: string;
  disabled?: boolean;
  required?: boolean;
  inputId?: string;
}) {
  const generatedId = useId();
  const id = inputId || `searchable-select-${generatedId}`;
  const listboxId = `${id}-listbox`;
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const activeOptionId = `${listboxId}-option-${activeIndex}`;

  const selectedOption = useMemo(
    () => options.find((option) => String(option.value) === String(value ?? "")) || null,
    [options, value],
  );

  useEffect(() => {
    if (!open) setQuery(selectedOption?.label || "");
  }, [open, selectedOption]);

  const filteredOptions = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle || query === selectedOption?.label) return options;
    return options.filter((option) => (
      `${option.label} ${option.searchText || ""}`.toLocaleLowerCase().includes(needle)
    ));
  }, [options, query, selectedOption?.label]);

  useEffect(() => {
    setActiveIndex((current) => Math.min(current, Math.max(0, filteredOptions.length - 1)));
  }, [filteredOptions.length]);

  useEffect(() => {
    if (open) document.getElementById(activeOptionId)?.scrollIntoView({ block: "nearest" });
  }, [activeOptionId, open]);

  useEffect(() => {
    function closeOnOutsideClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, []);

  function choose(option: SearchableSelectOption<T>) {
    onChange(option.value, option);
    setQuery(option.label);
    setOpen(false);
    inputRef.current?.focus();
  }

  return (
    <div ref={rootRef} className="relative">
      <div className={`input flex items-center gap-2 px-3 py-0 ${disabled ? "cursor-not-allowed bg-[#f4f2eb] opacity-70" : "bg-white"}`}>
        <Search className="h-4 w-4 shrink-0 text-[#8a8472]" aria-hidden="true" />
        <input
          ref={inputRef}
          id={id}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={open && filteredOptions.length ? activeOptionId : undefined}
          aria-required={required}
          className="h-full min-w-0 flex-1 bg-transparent text-sm outline-none"
          value={query}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          onFocus={(event) => {
            setOpen(true);
            event.currentTarget.select();
          }}
          onChange={(event) => {
            setQuery(event.target.value);
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
              setActiveIndex((current) => Math.min(current + 1, Math.max(0, filteredOptions.length - 1)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              setActiveIndex((current) => Math.max(0, current - 1));
            } else if (event.key === "Enter" && open && filteredOptions[activeIndex]) {
              event.preventDefault();
              choose(filteredOptions[activeIndex]);
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

      {open && !disabled && (
        <div
          id={listboxId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-md border border-[#d8d2c2] bg-white py-1 shadow-sm"
        >
          {filteredOptions.map((option, index) => {
            const selected = String(option.value) === String(value ?? "");
            return (
              <button
                type="button"
                role="option"
                id={`${listboxId}-option-${index}`}
                aria-selected={selected}
                key={String(option.value)}
                className={`flex w-full items-start gap-2 px-3 py-2 text-left text-sm ${index === activeIndex ? "bg-[#f3f0e7]" : "hover:bg-[#f8f6ef]"}`}
                onMouseEnter={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(option)}
              >
                <span className="min-w-0 flex-1 break-words">{option.label}</span>
                <Check className={`mt-0.5 h-4 w-4 shrink-0 ${selected ? "text-[#14110b]" : "invisible"}`} aria-hidden="true" />
              </button>
            );
          })}
          {filteredOptions.length === 0 && (
            <div className="px-3 py-3 text-sm text-[#8a8472]">{noResultsText}</div>
          )}
        </div>
      )}
    </div>
  );
}
