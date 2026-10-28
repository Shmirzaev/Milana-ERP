"use client";
import { useT } from "@/lib/i18n";

type Props = {
  page: number;
  pageSize: number;
  total: number;
  count: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  pageSizeOptions?: number[];
  position?: "top" | "bottom";
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
};

export default function PaginationControls({ page, total, count, onPageChange, position = "bottom", loading, error, onRetry }: Props) {
  const { t } = useT();
  const safeTotal = Number(total || 0);
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 border-[#ecebe3] px-4 py-3 text-sm text-[#56503f] ${position === "top" ? "mb-3 border-b" : "border-t"}`}>
      <div>{t("common.showingRange", { start: count ? 1 : 0, end: count, total: safeTotal })}</div>
      {error ? <button type="button" className="btn" onClick={onRetry}>{t("common.retry")}</button>
        : count < safeTotal && <button type="button" className="btn" disabled={loading} onClick={() => onPageChange(page + 1)}>
          {loading ? t("common.loading") : t("common.loadMore")}
        </button>}
    </div>
  );
}
