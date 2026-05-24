"use client";

type Props = {
  page: number;
  pageSize: number;
  total: number;
  count: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
};

export default function PaginationControls({ page, pageSize, total, count, onPageChange, onPageSizeChange }: Props) {
  const safeTotal = Number(total || 0);
  const start = safeTotal === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = safeTotal === 0 ? 0 : Math.min(safeTotal, start + count - 1);
  const hasPrev = page > 1;
  const hasNext = end < safeTotal;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#ecebe3] px-4 py-3 text-sm text-[#56503f]">
      <div>
        Showing {start}-{end} of {safeTotal} results
      </div>
      <div className="flex items-center gap-2">
        <select
          className="input h-8 w-24 py-1 text-xs"
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
        >
          {[25, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}
        </select>
        <button className="btn" disabled={!hasPrev} onClick={() => onPageChange(page - 1)}>Previous</button>
        <button className="btn" disabled={!hasNext} onClick={() => onPageChange(page + 1)}>Next</button>
      </div>
    </div>
  );
}
