"use client";
import { useMemo } from "react";
import { useSearchParams } from "next/navigation";
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
  const params = useSearchParams();
  const { t } = useT();
  const q = (params.get("q") || "").trim();
  const { data, isLoading } = useSWR<SearchResult[]>(
    q ? `/api/search?q=${encodeURIComponent(q)}` : null,
    fetcher,
  );

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

  return (
    <div>
      <PageHeader
        title={`${t("common.search")}${q ? `: "${q}"` : ""}`}
        subtitle={t("page.search.subtitle")}
      />

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
