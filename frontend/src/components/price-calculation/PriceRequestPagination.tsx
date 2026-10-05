"use client";

import { useT } from "@/lib/i18n";

export default function PriceRequestPagination({ hasMore, isLoadingMore, loadMore }: {
  hasMore: boolean;
  isLoadingMore: boolean;
  loadMore: () => void;
}) {
  const { t } = useT();
  if (!hasMore) return null;
  return <div className="flex justify-center py-4">
    <button className="btn" type="button" onClick={loadMore} disabled={isLoadingMore}>
      {t(isLoadingMore ? "common.loading" : "common.loadMore")}
    </button>
  </div>;
}
