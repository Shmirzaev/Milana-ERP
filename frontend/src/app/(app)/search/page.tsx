"use client";
import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";

import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type SearchResult = {
  type: "SalesOrder" | "Bundle" | "Model" | "Customer";
  id: number;
  label: string;
  url: string;
};

const TYPE_ORDER: SearchResult["type"][] = ["SalesOrder", "Bundle", "Model", "Customer"];

export default function SearchPage() {
  const router = useRouter();
  const params = useSearchParams();
  const { t } = useT();
  const q = (params.get("q") || "").trim();
  const [query, setQuery] = useState(q);
  const { data, isLoading } = useSWR<SearchResult[]>(
    q ? `/api/search?q=${encodeURIComponent(q)}` : null,
    fetcher,
  );

  useEffect(() => {
    setQuery(q);
  }, [q]);

  const grouped = useMemo(() => {
    const map: Record<string, SearchResult[]> = {};
    for (const type of TYPE_ORDER) map[type] = [];
    for (const row of data || []) {
      const key = row.type || "Model";
      if (!map[key]) map[key] = [];
      map[key].push(row);
    }
    return map;
  }, [data]);

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    const next = query.trim();
    router.push(next ? `/search?q=${encodeURIComponent(next)}` : "/search");
  }

  return (
    <div>
      <PageHeader
        title={`${t("common.search")}${q ? `: "${q}"` : ""}`}
        subtitle={t("page.search.subtitle")}
      />

      <form onSubmit={submitSearch} className="card mb-4 flex flex-col gap-2 p-3 sm:flex-row">
        <label className="sr-only" htmlFor="search-page-query">{t("common.search")}</label>
        <div className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-[#e3dfd3] bg-[#f8f6ef] px-3">
          <Search className="h-4 w-4 shrink-0 text-[#8a8472]" />
          <input
            id="search-page-query"
            className="h-10 min-w-0 flex-1 bg-transparent text-sm text-[#2c2920] placeholder:text-[#8a8472] focus:outline-none"
            placeholder={t("top.searchPlaceholder")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoComplete="off"
          />
        </div>
        <button type="submit" className="btn btn-primary h-10 justify-center sm:w-auto">{t("common.search")}</button>
      </form>

      {!q && <div className="card p-4 text-sm text-slate-600">{t("page.search.startHint")}</div>}
      {q && isLoading && <div className="card p-4 text-sm text-slate-600">{t("common.loading")}</div>}

      {q && !isLoading && (
        <div className="space-y-4">
          {TYPE_ORDER.map((type) => (
            <section key={type} className="card p-4">
              <div className="mb-2 text-sm font-semibold">
                {t(`search.type.${type}`)} ({grouped[type]?.length || 0})
              </div>
              {grouped[type]?.length ? (
                <ul className="space-y-1">
                  {grouped[type].map((row) => (
                    <li key={`${row.type}-${row.id}`}>
                      <a className="text-sm text-[#3b3528] underline" href={row.url}>
                        {row.label}
                      </a>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-sm text-slate-500">{t("page.search.noMatches")}</div>
              )}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
