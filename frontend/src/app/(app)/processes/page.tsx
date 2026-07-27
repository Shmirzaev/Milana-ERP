"use client";
import { Fragment, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ChevronDown, ChevronUp, Eye, ImageOff, Printer, RefreshCw, Search } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { formatBatchSerial } from "@/lib/batchSerial";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { useT } from "@/lib/i18n";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { FAST_LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";
import StagePipeline, { operationLabel, statusLabel } from "@/components/StagePipeline";

type Stage = {
  work_order_id: number;
  operation: string;
  status: string;
  planned: number;
  completed: number;
  failed: number;
  processed?: number;
  rework: number;
  progress_pct: number;
  assigned_to: number | null;
  sewing_flow_id: number | null;
  sewing_flow_code: string | null;
  sewing_flow_name: string | null;
  is_blocked?: boolean;
  block_reason?: string | null;
  deadline: string | null;
  overdue: boolean;
};

type ProcessBatch = {
  id: number;
  batch_no: string;
  batch_index: number;
  name: string | null;
  planned_quantity: number;
  start_date: string | null;
  deadline: string | null;
  current_stage: string;
  current_stage_status: string | null;
  current_sewing_flow: string | null;
  is_blocked?: boolean;
  blocked_by?: { work_order_id: number; operation: string; reason: string | null } | null;
  stages: Stage[];
};

type Process = {
  production_order_id: number;
  production_no: string;
  order_no?: string | null;
  production_type: string;
  po_status: string;
  po_deadline: string | null;
  po_overdue: boolean;
  planned_quantity: number;
  sales_order_id: number | null;
  sales_order_no: string | null;
  customer_name: string | null;
  model_code: string | null;
  model_name: string | null;
  model_image_url?: string | null;
  variant_picture_url?: string | null;
  material_image_url?: string | null;
  is_blocked?: boolean;
  blocked_by?: { work_order_id: number; operation: string; reason: string | null } | null;
  current_stage: string;
  current_stage_status: string | null;
  current_sewing_flow: string | null;
  stages: Stage[];
  batches?: ProcessBatch[];
};

type ProcessResponse = {
  rows: Process[];
  total: number;
  page: number;
  page_size: number;
};

const STAGE_COLORS: Record<string, string> = {
  cutting: "bg-rose-100 text-rose-800",
  printing: "bg-fuchsia-100 text-fuchsia-800",
  sewing: "bg-orange-100 text-orange-800",
  packaging: "bg-emerald-100 text-emerald-800",
  storage_transfer: "bg-cyan-100 text-cyan-800",
  planning_required: "bg-amber-100 text-amber-800",
  completed: "bg-slate-200 text-slate-700",
};

const STATUS_OPTIONS = [
  "",
  "new",
  "planning",
  "waiting_material",
  "cutting",
  "printing",
  "sewing",
  "packaging",
  "storage_transfer",
  "finished_storage",
];
const SORT_OPTIONS = [
  { value: "created_desc", labelKey: "page.processes.sortNewest" },
  { value: "created_asc", labelKey: "page.processes.sortOldest" },
  { value: "deadline_asc", labelKey: "page.processes.sortDeadlineAsc" },
  { value: "deadline_desc", labelKey: "page.processes.sortDeadlineDesc" },
  { value: "production_no_asc", labelKey: "page.processes.sortProductionAsc" },
  { value: "status_asc", labelKey: "page.processes.sortStatusAsc" },
];

function positiveInt(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function buildProcessUrl({ q, status, createdFrom, createdTo, sort, page, pageSize }: {
  q: string;
  status: string;
  createdFrom: string;
  createdTo: string;
  sort: string;
  page: number;
  pageSize: number;
}) {
  const params = new URLSearchParams({
    include_total: "true",
    page: String(page),
    page_size: String(pageSize),
    sort,
  });
  if (q.trim()) params.set("q", q.trim());
  if (status) params.set("status", status);
  if (createdFrom) params.set("created_from", createdFrom);
  if (createdTo) params.set("created_to", createdTo);
  return `/api/process-tracking?${params.toString()}`;
}

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleDateString() : "-";
}

export default function ProcessTrackingPage() {
  const { t } = useT();
  const searchParams = useSearchParams();
  const searchString = searchParams.toString();

  const [search, setSearch] = useState(() => searchParams.get("q") ?? "");
  const [debouncedSearch, setDebouncedSearch] = useState(() => searchParams.get("q") ?? "");
  const [status, setStatus] = useState(() => searchParams.get("status") ?? "");
  const [createdFrom, setCreatedFrom] = useState(() => searchParams.get("created_from") ?? "");
  const [createdTo, setCreatedTo] = useState(() => searchParams.get("created_to") ?? "");
  const [sort, setSort] = useState(() => searchParams.get("sort") ?? "created_desc");
  const [page, setPage] = useState(() => positiveInt(searchParams.get("page"), 1));
  const [pageSize, setPageSize] = useState(() => positiveInt(searchParams.get("page_size"), 25));
  const [expanded, setExpanded] = useState<number | null>(null);
  const [manualRefreshing, setManualRefreshing] = useState(false);

  useEffect(() => {
    const nextQ = searchParams.get("q") ?? "";
    setSearch(nextQ);
    setDebouncedSearch(nextQ);
    setStatus(searchParams.get("status") ?? "");
    setCreatedFrom(searchParams.get("created_from") ?? "");
    setCreatedTo(searchParams.get("created_to") ?? "");
    setSort(searchParams.get("sort") ?? "created_desc");
    setPage(positiveInt(searchParams.get("page"), 1));
    setPageSize(positiveInt(searchParams.get("page_size"), 25));
  }, [searchParams, searchString]);

  useEffect(() => {
    const id = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(id);
  }, [search]);

  useEffect(() => {
    setPage(1);
  }, [createdFrom, createdTo, debouncedSearch, status, sort, pageSize]);

  const processUrl = useMemo(
    () => buildProcessUrl({ q: debouncedSearch, status, createdFrom, createdTo, sort, page, pageSize }),
    [createdFrom, createdTo, debouncedSearch, status, sort, page, pageSize],
  );
  const { data, error, isLoading, mutate } = useSWR<ProcessResponse>(
    processUrl,
    fetcher,
    { ...FAST_LIVE_DATA_SWR_OPTIONS, keepPreviousData: true },
  );

  async function refreshNow() {
    if (manualRefreshing) return;
    setManualRefreshing(true);
    try {
      await mutate();
    } finally {
      setManualRefreshing(false);
    }
  }

  function openExport() {
    api.openLabel("/api/process-tracking/export");
  }

  const rows = data?.rows ?? [];
  const total = data?.total ?? 0;
  const activePage = data?.page ?? page;
  const activePageSize = data?.page_size ?? pageSize;
  const overdueOnPage = rows.filter((p) => p.po_overdue || p.stages.some((s) => s.overdue)).length;
  const hasFilters = Boolean(debouncedSearch.trim() || status || createdFrom || createdTo);
  const emptyMessage = hasFilters ? t("page.processes.filteredEmpty") : t("page.processes.empty");
  const loadingFirstPage = isLoading && !data;

  return (
    <div>
      <PageHeader
        title={t("page.processes.title")}
        subtitle={t("page.processes.subtitle")}
        actions={(
          <div className="flex gap-2">
            <button
              className="btn"
              onClick={refreshNow}
              disabled={manualRefreshing}
              title={t("page.processes.refresh")}
              aria-label={t("page.processes.refresh")}
            >
              <RefreshCw />
              {manualRefreshing ? t("common.loading") : t("page.processes.refresh")}
            </button>
            <button className="btn" onClick={openExport}>
              <Printer />
              {t("page.processes.exportPrint")}
            </button>
          </div>
        )}
      />

      {error && !data && (
        <div className="card mb-4 border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {String((error as any).message ?? error)}
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_12rem_12rem_12rem_12rem_13rem]">
        <label className="block">
          <span className="label">{t("common.search")}</span>
          <span className="relative block">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
            <input
              className="input pl-9"
              placeholder={t("page.processes.searchPlaceholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              name="process-search"
              autoComplete="off"
            />
          </span>
        </label>
        <label className="block">
          <span className="label">{t("common.status")}</span>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} name="process-status">
            {STATUS_OPTIONS.map((option) => (
              <option key={option || "all"} value={option}>
                {option ? statusLabel(option, t) : t("common.all")}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label">{t("page.processes.sort")}</span>
          <select className="input" value={sort} onChange={(e) => setSort(e.target.value)} name="process-sort">
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="label">{t("common.createdFrom")}</span>
          <input className="input" type="date" value={createdFrom} onChange={(e) => setCreatedFrom(e.target.value)} />
        </label>
        <label className="block">
          <span className="label">{t("common.createdTo")}</span>
          <input className="input" type="date" value={createdTo} onChange={(e) => setCreatedTo(e.target.value)} />
        </label>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-1">
          <SummaryStat label={t("page.processes.totalMatching")} value={total.toLocaleString()} />
          <SummaryStat label={t("page.processes.overdueOnPage")} value={overdueOnPage.toLocaleString()} tone={overdueOnPage ? "danger" : undefined} />
        </div>
      </div>

      <div className="card hidden overflow-x-auto md:block">
        <table className="table min-w-[1180px]">
          <thead>
            <tr>
              <th>{t("page.processes.references")}</th>
              <th>{t("field.customer")}</th>
              <th>{t("field.model")}</th>
              <th>{t("field.qty")}</th>
              <th>{t("page.processes.currentStage")}</th>
              <th>{t("page.processes.assignedFlow")}</th>
              <th>{t("page.processes.deadline")}</th>
              <th className="sticky right-0 z-10 border-l border-[#e3dfd3] bg-[#f1efe8]">{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {loadingFirstPage && (
              <tr><td colSpan={8} className="text-[#8a8472]">{t("common.loading")}</td></tr>
            )}
            {!loadingFirstPage && rows.length === 0 && (
              <tr><td colSpan={8} className="text-[#8a8472]">{emptyMessage}</td></tr>
            )}
            {rows.map((p) => (
              <Fragment key={p.production_order_id}>
                <tr>
                  <td className="w-[220px]">
                    <ProcessReference process={p} />
                  </td>
                  <td className="max-w-[180px] truncate" title={p.customer_name || ""}>{p.customer_name || "-"}</td>
                  <td className="max-w-[320px]">
                    <ModelCell process={p} />
                  </td>
                  <td>
                    {p.planned_quantity}
                    {(p.batches || []).length > 0 && (
                      <div className="mt-0.5 text-[10px] text-[#8a8472]">{t("batch.count", { count: (p.batches || []).length })}</div>
                    )}
                  </td>
                  <td className="min-w-[300px]">
                    <StageSummary process={p} />
                  </td>
                  <td className="max-w-[150px] truncate" title={p.current_sewing_flow || ""}>{p.current_sewing_flow || "-"}</td>
                  <td className={p.po_overdue ? "font-medium text-red-600" : ""}>{formatDate(p.po_deadline)}</td>
                  <td className="sticky right-0 border-l border-[#ecebe3] bg-[#fdfcf8]">
                    <ProcessActions
                      process={p}
                      expanded={expanded === p.production_order_id}
                      onToggle={() => setExpanded(expanded === p.production_order_id ? null : p.production_order_id)}
                    />
                  </td>
                </tr>
                {expanded === p.production_order_id && (
                  <tr>
                    <td colSpan={8} className="bg-slate-50 p-3">
                      <ExpandedProcess process={p} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        <PaginationControls
          page={activePage}
          pageSize={activePageSize}
          total={total}
          count={rows.length}
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>

      <div className="grid gap-3 md:hidden">
        {loadingFirstPage && <div className="card p-4 text-sm text-[#8a8472]">{t("common.loading")}</div>}
        {!loadingFirstPage && rows.length === 0 && <div className="card p-4 text-sm text-[#8a8472]">{emptyMessage}</div>}
        {rows.map((p) => (
          <article key={p.production_order_id} className="card p-4">
            <div className="flex items-start justify-between gap-3">
              <ProcessReference process={p} />
              <span className={`badge ${STAGE_COLORS[p.current_stage] || "badge"}`}>{operationLabel(p.current_stage, t)}</span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
              <FieldValue label={t("field.customer")} value={p.customer_name || "-"} />
              <div className="col-span-2">
                <div className="text-[10px] font-semibold text-[#8a8472]">{t("field.model")}</div>
                <div className="mt-1">
                  <ModelCell process={p} />
                </div>
              </div>
              <FieldValue label={t("field.qty")} value={String(p.planned_quantity)} />
              <FieldValue label={t("page.processes.deadline")} value={formatDate(p.po_deadline)} danger={p.po_overdue} />
              <FieldValue label={t("page.processes.assignedFlow")} value={p.current_sewing_flow || "-"} wide />
              <FieldValue label={t("common.status")} value={p.current_stage_status ? statusLabel(p.current_stage_status, t) : "-"} wide />
            </div>
            <div className="mt-3 overflow-x-auto">
              <StagePipeline currentStage={p.current_stage} stages={p.stages} compact />
            </div>
            {p.is_blocked && p.blocked_by && (
              <div className="mt-2 text-xs text-red-700" title={p.blocked_by.reason ?? ""}>
                {t("page.processes.blockedOn", { operation: operationLabel(p.blocked_by.operation, t) })}
              </div>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              <Link href={`/production-orders/${p.production_order_id}`} className="btn btn-primary">
                <Eye />
                {t("btn.view")}
              </Link>
              <button
                type="button"
                onClick={() => setExpanded(expanded === p.production_order_id ? null : p.production_order_id)}
                className="btn"
              >
                {expanded === p.production_order_id ? <ChevronUp /> : <ChevronDown />}
                {t("page.processes.stagesHeader")}
              </button>
            </div>
            {expanded === p.production_order_id && (
              <div className="mt-4 border-t border-[#ecebe3] pt-3">
                <ExpandedProcess process={p} />
              </div>
            )}
          </article>
        ))}
        <div className="card">
          <PaginationControls
            page={activePage}
            pageSize={activePageSize}
            total={total}
            count={rows.length}
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
          />
        </div>
      </div>
    </div>
  );
}

function SummaryStat({ label, value, tone }: { label: string; value: string; tone?: "danger" }) {
  return (
    <div className="panel px-3 py-2">
      <div className="text-[11px] font-semibold text-[#8a8472]">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold ${tone === "danger" ? "text-red-600" : "text-[#14110b]"}`}>{value}</div>
    </div>
  );
}

function ProcessReference({ process }: { process: Process }) {
  const { t } = useT();
  const productionNo = process.production_no || process.order_no || `#${process.production_order_id}`;
  const salesOrderNo = process.sales_order_no;
  return (
    <div className="space-y-1 text-sm" data-testid="process-reference">
      <div>
        <div className="text-[10px] font-semibold text-[#8a8472]">{t("field.productionNo")}</div>
        <Link href={`/production-orders/${process.production_order_id}`} className="mono font-semibold text-brand-600 hover:underline">
          {productionNo}
        </Link>
      </div>
      {salesOrderNo && (
        <div>
          <div className="text-[10px] font-semibold text-[#8a8472]">{t("field.salesOrderNo")}</div>
          {process.sales_order_id ? (
            <Link href={`/sales-orders/${process.sales_order_id}`} className="mono text-[#56503f] hover:underline">
              {salesOrderNo}
            </Link>
          ) : (
            <span className="mono text-[#56503f]">{salesOrderNo}</span>
          )}
        </div>
      )}
    </div>
  );
}

function StageSummary({ process }: { process: Process }) {
  const { t } = useT();
  return (
    <div>
      <StagePipeline currentStage={process.current_stage} stages={process.stages} compact={false} />
      <div className="mt-1">
        <span className={`badge ${STAGE_COLORS[process.current_stage] || "badge"}`}>{operationLabel(process.current_stage, t)}</span>
      </div>
      {process.current_stage_status && (
        <div className="mt-1 text-xs text-[#8a8472]">{statusLabel(process.current_stage_status, t)}</div>
      )}
      {process.is_blocked && process.blocked_by && (
        <div className="mt-1 text-xs text-red-700" title={process.blocked_by.reason ?? ""}>
          {t("page.processes.blockedOn", { operation: operationLabel(process.blocked_by.operation, t) })}
        </div>
      )}
    </div>
  );
}

function ProcessActions({ process, expanded, onToggle }: { process: Process; expanded: boolean; onToggle: () => void }) {
  const { t } = useT();
  return (
    <div className="flex min-w-[142px] flex-col gap-1">
      <Link href={`/production-orders/${process.production_order_id}`} className="btn h-8 px-2">
        <Eye />
        {t("btn.view")}
      </Link>
      <button type="button" onClick={onToggle} className="btn h-8 px-2">
        {expanded ? <ChevronUp /> : <ChevronDown />}
        {t("page.processes.stagesHeader")}
      </button>
      <Link
        href={`/admin/audit-logs?entity=ProductionOrder&id=${process.production_order_id}`}
        className="px-1 text-xs text-[#8a8472] hover:underline"
      >
        {t("page.processes.audit")}
      </Link>
    </div>
  );
}

function PictureThumb({ imageUrl, alt, placeholder = false }: { imageUrl?: string | null; alt: string; placeholder?: boolean }) {
  const src = storageThumbnailUrl(imageUrl, 160);
  if (src) {
    return (
      <a href={imagePreviewHref(imageUrl, alt)} target="_blank" rel="noreferrer" className="h-14 w-14 shrink-0 overflow-hidden rounded-md border border-[#e3dfd3] bg-[#f1efe8]">
        <img
          src={src}
          alt={alt}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      </a>
    );
  }
  if (!placeholder) return null;
  return (
    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-md border border-[#e3dfd3] bg-[#f1efe8] text-[#8a8472]">
      <ImageOff className="h-4 w-4" />
    </div>
  );
}

function ModelCell({ process }: { process: Process }) {
  const modelAlt = process.model_name || process.model_code || "Model";
  const variantAlt = process.model_code ? `${process.model_code} variant` : "Variant";
  const showVariant = Boolean(process.variant_picture_url && process.variant_picture_url !== process.model_image_url);
  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className="flex shrink-0 gap-1.5">
        <PictureThumb imageUrl={process.model_image_url} alt={modelAlt} placeholder />
        {showVariant && <PictureThumb imageUrl={process.variant_picture_url} alt={variantAlt} />}
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm font-medium" title={process.model_code || ""}>{process.model_code || "-"}</div>
        <div className="truncate text-xs text-[#8a8472]" title={process.model_name || ""}>{process.model_name || "-"}</div>
      </div>
    </div>
  );
}

function FieldValue({ label, value, danger, wide }: { label: string; value: string; danger?: boolean; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2" : ""}>
      <div className="text-[10px] font-semibold text-[#8a8472]">{label}</div>
      <div className={`mt-0.5 break-words ${danger ? "font-medium text-red-600" : "text-[#2c2920]"}`}>{value}</div>
    </div>
  );
}

function ExpandedProcess({ process }: { process: Process }) {
  const { t } = useT();
  return (
    <div>
      <div className="mb-2 text-xs font-medium text-[#8a8472]">{t("page.processes.stagesHeader")}</div>
      <StageRowsTable stages={process.stages} />

      {(process.batches || []).length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="text-xs font-medium text-[#8a8472]">{t("page.processes.batchTracking")}</div>
          {(process.batches || []).map((batch) => (
            <details key={batch.id} className="rounded-md border border-slate-200 bg-white">
              <summary className="cursor-pointer list-none px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="badge shrink-0">{formatBatchSerial(batch, process.production_order_id)}</span>
                    <span className="truncate text-sm font-medium">{batch.name || `Batch ${batch.batch_index}`}</span>
                    <span className="text-xs text-[#8a8472]">{batch.planned_quantity} {t("field.unitPcs")}</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className={`badge ${STAGE_COLORS[batch.current_stage] || "badge"}`}>
                      {operationLabel(batch.current_stage, t)}
                    </span>
                    {batch.current_stage_status && <span>{statusLabel(batch.current_stage_status, t)}</span>}
                    <span>{batch.deadline ? new Date(batch.deadline).toLocaleDateString() : t("page.processes.noDeadline")}</span>
                  </div>
                </div>
              </summary>
              <div className="border-t border-slate-200 p-3">
                <div className="overflow-x-auto">
                  <StagePipeline currentStage={batch.current_stage} stages={batch.stages} compact={false} />
                </div>
                <div className="mt-2">
                  <StageRowsTable stages={batch.stages} />
                </div>
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

function StageRowsTable({ stages }: { stages: Stage[] }) {
  const { t } = useT();
  return (
    <div className="overflow-x-auto">
      <table className="table text-xs">
        <thead>
          <tr>
            <th>{t("field.operation")}</th>
            <th>{t("common.status")}</th>
            <th>{t("page.processes.progress")}</th>
            <th>{t("field.passed")} / {t("field.failed")}</th>
            <th>{t("page.processes.assignedFlow")}</th>
            <th>{t("page.processes.deadline")}</th>
          </tr>
        </thead>
        <tbody>
          {stages.map((s) => {
            const processed = Number(s.processed ?? s.completed ?? 0);
            return (
            <tr key={s.work_order_id}>
              <td>
                <span className={`badge ${STAGE_COLORS[s.operation] || "badge"}`}>{operationLabel(s.operation, t)}</span>
              </td>
              <td>{statusLabel(s.status, t)}</td>
              <td>
                <div className="h-2 w-32 overflow-hidden rounded bg-slate-200">
                  <div
                    className="h-full bg-brand-500"
                    style={{ width: `${Math.min(100, s.progress_pct)}%` }}
                  />
                </div>
                <div className="mt-0.5 text-[10px] text-[#8a8472]">{processed}/{s.planned} ({s.progress_pct}%)</div>
              </td>
              <td>{s.completed} / {s.failed}</td>
              <td>{s.sewing_flow_code || "-"}</td>
              <td className={s.overdue ? "text-red-600" : ""}>
                {formatDate(s.deadline)}
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
