"use client";
import { useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { Search } from "lucide-react";
import { fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { useT } from "@/lib/i18n";

type AuditChange = {
  field: string;
  from: unknown;
  to: unknown;
};

type AuditRow = {
  id: number;
  user_id?: number | null;
  user_name?: string | null;
  user?: { id: number; name: string; email?: string | null } | null;
  action: string;
  action_label?: string;
  entity_type: string;
  entity_label?: string;
  entity_id?: number | null;
  old_value?: Record<string, unknown> | null;
  new_value?: Record<string, unknown> | null;
  changed_fields?: AuditChange[];
  summary?: string;
  root_cause_hint?: string;
  created_at: string;
};

const ACTIONS = [
  "create",
  "update",
  "delete",
  "approve",
  "confirm",
  "start",
  "complete",
  "receive",
  "ship",
  "deliver",
  "block",
  "unblock",
];

const ENTITIES = [
  "SalesOrder",
  "ProductionOrder",
  "WorkOrder",
  "Bundle",
  "Package",
  "Shipment",
  "StockBatch",
  "StockMovement",
  "User",
  "Task",
  "SystemSetting",
];

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatWhen(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function buildQuery({
  page,
  pageSize,
  query,
  userId,
  entityType,
  entityId,
  action,
  dateFrom,
  dateTo,
}: {
  page: number;
  pageSize: number;
  query: string;
  userId: string;
  entityType: string;
  entityId: string;
  action: string;
  dateFrom: string;
  dateTo: string;
}) {
  const params = new URLSearchParams({
    include_total: "true",
    page: String(page),
    page_size: String(pageSize),
  });
  if (query.trim()) params.set("q", query.trim());
  if (userId.trim()) params.set("user_id", userId.trim());
  if (entityType.trim()) params.set("entity_type", entityType.trim());
  if (entityId.trim()) params.set("entity_id", entityId.trim());
  if (action.trim()) params.set("action", action.trim());
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return `/api/audit-logs?${params.toString()}`;
}

export default function AuditLogsPage() {
  const { t } = useT();
  const params = useSearchParams();
  const [query, setQuery] = useState(params?.get("q") ?? "");
  const [userId, setUserId] = useState(params?.get("user") ?? "");
  const [entityType, setEntityType] = useState(params?.get("entity") ?? "");
  const [entityId, setEntityId] = useState(params?.get("id") ?? "");
  const [action, setAction] = useState(params?.get("action") ?? "");
  const [dateFrom, setDateFrom] = useState(params?.get("from") ?? "");
  const [dateTo, setDateTo] = useState(params?.get("to") ?? "");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [openId, setOpenId] = useState<number | null>(null);

  const url = useMemo(
    () => buildQuery({ page, pageSize, query, userId, entityType, entityId, action, dateFrom, dateTo }),
    [page, pageSize, query, userId, entityType, entityId, action, dateFrom, dateTo],
  );
  const { data: pageData, isLoading } = useSWR<any>(url, fetcher);
  const rows: AuditRow[] = pageData?.rows || [];

  function resetFilters() {
    setQuery("");
    setUserId("");
    setEntityType("");
    setEntityId("");
    setAction("");
    setDateFrom("");
    setDateTo("");
    setPage(1);
  }

  function updateFilter(setter: (value: string) => void, value: string) {
    setter(value);
    setPage(1);
  }

  return (
    <div>
      <PageHeader title={t("page.admin.audit.title")} subtitle={t("page.admin.audit.subtitle")} />

      <section className="panel mb-4 p-3 sm:p-4">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-semibold text-[#14110b]">{t("page.admin.audit.managerView")}</div>
            <p className="mt-1 text-sm text-[#8a8472]">{t("page.admin.audit.managerHelp")}</p>
          </div>
          <button className="btn w-full sm:w-auto" onClick={resetFilters}>{t("common.clear")}</button>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-6">
          <label className="xl:col-span-2">
            <span className="label">{t("common.search")}</span>
            <div className="flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 shadow-sm">
              <Search className="h-4 w-4 shrink-0 text-[#8a8472]" />
              <input
                className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none"
                placeholder={t("page.admin.audit.searchPlaceholder")}
                value={query}
                onChange={(e) => updateFilter(setQuery, e.target.value)}
              />
            </div>
          </label>
          <label>
            <span className="label">{t("field.user")}</span>
            <input className="input" inputMode="numeric" placeholder={t("page.admin.audit.userId")} value={userId} onChange={(e) => updateFilter(setUserId, e.target.value)} />
          </label>
          <label>
            <span className="label">{t("field.action")}</span>
            <select className="input" value={action} onChange={(e) => updateFilter(setAction, e.target.value)}>
              <option value="">{t("common.all")}</option>
              {ACTIONS.map((item) => <option key={item} value={item}>{item.replace(/_/g, " ")}</option>)}
            </select>
          </label>
          <label>
            <span className="label">{t("field.entity")}</span>
            <select className="input" value={entityType} onChange={(e) => updateFilter(setEntityType, e.target.value)}>
              <option value="">{t("common.all")}</option>
              {ENTITIES.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label>
            <span className="label">{t("field.id")}</span>
            <input className="input" inputMode="numeric" placeholder="123" value={entityId} onChange={(e) => updateFilter(setEntityId, e.target.value)} />
          </label>
          <label>
            <span className="label">{t("field.from")}</span>
            <input className="input" type="date" value={dateFrom} onChange={(e) => updateFilter(setDateFrom, e.target.value)} />
          </label>
          <label>
            <span className="label">{t("field.to")}</span>
            <input className="input" type="date" value={dateTo} onChange={(e) => updateFilter(setDateTo, e.target.value)} />
          </label>
        </div>
      </section>

      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#ecebe3] px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-[#14110b]">{t("page.admin.audit.timeline")}</div>
            <div className="text-xs text-[#8a8472]">{isLoading ? t("common.loading") : t("common.matches", { count: Number(pageData?.total || 0) })}</div>
          </div>
        </div>

        <div className="divide-y divide-[#ecebe3]">
          {rows.map((row) => {
            const changes = row.changed_fields || [];
            const isOpen = openId === row.id;
            return (
              <article key={row.id} className="p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-[#8a8472]">
                      <span className="badge">{formatWhen(row.created_at)}</span>
                      <span>{row.user?.name || row.user_name || `User #${row.user_id || "-"}`}</span>
                      <span>/</span>
                      <span>{row.entity_label || row.entity_type} #{row.entity_id || "-"}</span>
                    </div>
                    <h2 className="mt-2 text-base font-semibold text-[#14110b]">{row.summary || `${row.action} ${row.entity_type}`}</h2>
                    <p className="mt-1 text-sm text-[#56503f]">{row.root_cause_hint || t("page.admin.audit.defaultHint")}</p>
                    {changes.length ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {changes.slice(0, 4).map((change) => (
                          <span key={`${row.id}-${change.field}`} className="badge bg-[#f8f6ef] text-[#2c2920]">
                            {change.field.replace(/_/g, " ")}: {formatValue(change.from)} -&gt; {formatValue(change.to)}
                          </span>
                        ))}
                        {changes.length > 4 ? <span className="badge">+{changes.length - 4}</span> : null}
                      </div>
                    ) : null}
                  </div>
                  <button className="btn w-full lg:w-auto" onClick={() => setOpenId(isOpen ? null : row.id)}>
                    {isOpen ? t("page.admin.audit.hideDetails") : t("page.admin.audit.showDetails")}
                  </button>
                </div>

                {isOpen ? (
                  <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
                    <div className="rounded-md border border-[#e3dfd3] bg-[#f8f6ef] p-3">
                      <div className="mb-2 text-xs font-semibold uppercase text-[#8a8472]">{t("page.admin.audit.before")}</div>
                      <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-xs text-[#2c2920]">{JSON.stringify(row.old_value || {}, null, 2)}</pre>
                    </div>
                    <div className="rounded-md border border-[#e3dfd3] bg-[#f8f6ef] p-3">
                      <div className="mb-2 text-xs font-semibold uppercase text-[#8a8472]">{t("page.admin.audit.after")}</div>
                      <pre className="max-h-56 overflow-auto whitespace-pre-wrap text-xs text-[#2c2920]">{JSON.stringify(row.new_value || {}, null, 2)}</pre>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}

          {!isLoading && rows.length === 0 ? (
            <div className="p-8 text-center text-sm text-[#8a8472]">{t("page.admin.audit.empty")}</div>
          ) : null}
        </div>

        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={Number(pageData?.total || 0)}
          count={rows.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </section>
    </div>
  );
}
