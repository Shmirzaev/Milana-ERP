"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { CalendarCheck, Clock3, FileText, PackageCheck, Search, Truck, WalletCards, X } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import PaginationControls from "@/components/PaginationControls";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { productionTypeLabel, statusLabel } from "@/components/StagePipeline";
import { orderReference } from "@/lib/orderRef";

type HistorySummary = {
  ordered_qty: number;
  planned_qty: number;
  cut_qty: number;
  sewn_qty: number;
  packaged_qty: number;
  shipped_qty: number;
  package_count: number;
  shipment_count: number;
  invoice_count: number;
  payment_count: number;
  order_amount: number;
  paid_total: number;
  outstanding_amount: number;
  material_spent_cost: number;
  ordered_at?: string | null;
  completed_at?: string | null;
  last_activity_at?: string | null;
  material_spent?: MaterialSpent[];
};

type HistoryRow = {
  id: number;
  record_type: "sales_order" | "production_order";
  history_key: string;
  order_no: string;
  customer_id?: number | null;
  customer_name?: string | null;
  group_order_no?: string | null;
  ordered_for?: string | null;
  order_type: string;
  status: string;
  deadline?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  last_activity_at?: string | null;
  total_amount: number;
  products?: HistoryProduct[];
  summary: HistorySummary;
};

type HistoryProduct = {
  model_id: number;
  model_no?: string | null;
  variant_no?: string | null;
  code?: string | null;
  name?: string | null;
  picture_url?: string | null;
};

type ModelRef = {
  code?: string | null;
  name?: string | null;
  translations?: Record<string, string> | null;
};

type OrderItem = {
  id: number;
  model?: ModelRef | null;
  model_id: number;
  color: string;
  size: string;
  quantity: number;
  unit_price: number;
  line_total: number;
  printing_required?: boolean;
};

type MaterialSpent = {
  item_id: number;
  sku: string;
  name: string;
  category: string;
  unit: string;
  quantity: number;
  estimated_cost: number;
};

type ProductionOrder = {
  id: number;
  production_no: string;
  order_no?: string | null;
  status: string;
  planned_quantity: number;
  deadline?: string | null;
  estimated_material_code?: string | null;
  estimated_material_amount?: number | null;
  estimated_material_unit?: string | null;
  work_orders: {
    id: number;
    order_no?: string | null;
    operation: string;
    status: string;
    production_batch_id?: number | null;
    planned_output_qty: number;
    actual_output_qty: number;
    passed_qty: number;
    failed_qty: number;
    start_time?: string | null;
    end_time?: string | null;
  }[];
};

type PackageRow = {
  id: number;
  package_no: string;
  barcode: string;
  status: string;
  total_quantity: number;
  weight_kg?: number | null;
  packed_at?: string | null;
  received_at?: string | null;
  shipped_at?: string | null;
};

type ShipmentRow = {
  id: number;
  shipment_no: string;
  status: string;
  shipped_at?: string | null;
  delivered_at?: string | null;
  packages: { package_id: number; quantity: number }[];
};

type InvoiceRow = {
  id: number;
  invoice_no: string;
  amount: number;
  status: string;
  issued_at?: string | null;
  due_date?: string | null;
};

type PaymentRow = {
  id: number;
  invoice_id?: number | null;
  amount: number;
  payment_method?: string | null;
  paid_at?: string | null;
};

type TimelineEvent = {
  type: string;
  title: string;
  at?: string | null;
  meta?: Record<string, any>;
};

type HistoryDetail = HistoryRow & {
  order?: Record<string, any>;
  items: OrderItem[];
  production_orders: ProductionOrder[];
  materials: { spent: MaterialSpent[] };
  packages: PackageRow[];
  shipments: ShipmentRow[];
  invoices: InvoiceRow[];
  payments: PaymentRow[];
  step_records?: Record<string, Record<string, any>[]>;
  timeline: TimelineEvent[];
};

type DetailTab = "overview" | "planning" | "production" | "materials" | "packages" | "finance" | "timeline";

function money(value: number) {
  return `$${Number(value || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function qty(value: number, unit = "") {
  const formatted = Number(value || 0).toLocaleString("en-US", { maximumFractionDigits: 2 });
  return unit ? `${formatted} ${unit}` : formatted;
}

function dateOnly(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleDateString();
}

function dateTime(value?: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function readableField(value: string) {
  const labels: Record<string, string> = {
    id: "Record ID",
    item_id: "Material ID",
    reference_id: "Source record ID",
    reference_type: "Source process",
    production_order_id: "Production order ID",
    production_batch_id: "Production batch ID",
    sales_order_id: "Sales order ID",
    work_order_id: "Work order ID",
    department_id: "Department ID",
    warehouse_id: "Warehouse ID",
    created_by: "Created by user",
    updated_by: "Updated by user",
  };
  if (labels[value]) return labels[value];
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function readableValue(value: string) {
  return value
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function shouldShowLedgerField(key: string, value: any) {
  if (value === null || value === undefined || value === "") return false;
  return key !== "id" && !key.endsWith("_id");
}

function ledgerScalar(key: string, value: any) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (key.endsWith("_at") || key === "deadline" || key === "start_date" || key === "end_time" || key === "start_time") {
    return dateTime(String(value));
  }
  if (["status", "operation", "movement_type", "reference_type", "reservation_type", "source", "category", "action", "scan_type"].includes(key)) {
    return readableValue(String(value));
  }
  return String(value);
}

function LedgerValue({ fieldKey, value }: { fieldKey: string; value: any }) {
  if (Array.isArray(value)) {
    if (!value.length) return <span className="text-[#8a8472]">None</span>;
    return (
      <div className="space-y-3">
        {value.map((entry, index) => (
          <div key={entry?.id ?? index} className="border-l-2 border-[#ded9ca] pl-3">
            {typeof entry === "object" && entry !== null
              ? <LedgerValue fieldKey={fieldKey} value={entry} />
              : ledgerScalar(fieldKey, entry)}
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === "object" && value !== null) {
    if (fieldKey === "item") {
      return <span>{[value.sku, value.name, value.category ? readableValue(value.category) : null].filter(Boolean).join(" — ")}</span>;
    }
    if (fieldKey === "batch") {
      return (
        <span>
          {[value.batch_no ? `Batch ${value.batch_no}` : null, value.cost_per_unit != null ? `Cost per unit ${value.cost_per_unit}` : null].filter(Boolean).join(" — ")}
        </span>
      );
    }
    if (fieldKey === "model") return <span>{modelLabel(value, value.id || "-")}</span>;

    const entries = Object.entries(value).filter(([key, nested]) => shouldShowLedgerField(key, nested));
    return (
      <dl className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
        {entries.map(([key, nested]) => (
          <div key={key} className="min-w-0">
            <dt className="text-xs text-[#8a8472]">{readableField(key)}</dt>
            <dd className="mt-0.5 break-words text-sm text-[#14110b]"><LedgerValue fieldKey={key} value={nested} /></dd>
          </div>
        ))}
      </dl>
    );
  }

  return <span>{ledgerScalar(fieldKey, value)}</span>;
}

function LedgerRecordGroup({ title, rows }: { title: string; rows: Record<string, any>[] }) {
  if (!rows.length) return null;
  return (
    <section className="border-b border-[#ecebe3] last:border-b-0">
      <div className="bg-[#f8f7f3] px-4 py-2 text-sm font-semibold text-[#14110b]">{title} ({rows.length})</div>
      <div className="divide-y divide-[#ecebe3]">
        {rows.map((row, index) => {
          const entries = Object.entries(row).filter(([key, value]) => shouldShowLedgerField(key, value));
          return (
            <dl key={`${title}-${row.id ?? index}`} className="grid grid-cols-1 gap-x-4 gap-y-3 px-4 py-4 sm:grid-cols-2 xl:grid-cols-3">
              {entries.map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="text-xs text-[#8a8472]">{readableField(key)}</dt>
                  <dd className="mt-1 break-words text-sm text-[#14110b]">
                    <LedgerValue fieldKey={key} value={value} />
                  </dd>
                </div>
              ))}
            </dl>
          );
        })}
      </div>
    </section>
  );
}

function detailedRecordGroups(detail: HistoryDetail) {
  const productionOrders = detail.production_orders as any[];
  const orderRecord = detail.order
    ? {
        ...Object.fromEntries(
          Object.entries(detail.order).filter(([key, value]) => !["items", "model", "printing", "batches", "work_orders"].includes(key) && (typeof value !== "object" || value === null)),
        ),
        ...(detail.order.model ? { model: modelLabel(detail.order.model, detail.order.model_id) } : {}),
      }
    : null;
  const planning = productionOrders.map((order) => ({
    ...Object.fromEntries(
      Object.entries(order).filter(([key]) => !["items", "batches", "work_orders", "model"].includes(key)),
    ),
    model: modelLabel(order.model, order.model_id),
  }));
  const batches = productionOrders.flatMap((order) => order.batches || []);
  const workOrders = productionOrders.flatMap((order) => order.work_orders || []);
  const groups: { key: string; rows: Record<string, any>[] }[] = [
    { key: "order", rows: orderRecord ? [orderRecord] : [] },
    { key: "production planning", rows: planning },
    { key: "production batches", rows: batches },
    { key: "work orders", rows: workOrders },
    { key: "material movements", rows: (detail.materials as any).movements || [] },
    ...Object.entries(detail.step_records || {}).map(([key, rows]) => ({ key, rows })),
    { key: "packages and storage", rows: detail.packages as any[] },
    { key: "shipments", rows: detail.shipments as any[] },
    { key: "invoices", rows: detail.invoices as any[] },
    { key: "payments", rows: detail.payments as any[] },
  ];
  return groups.filter((group) => group.rows.length > 0);
}

function recordGroupsForTab(detail: HistoryDetail, tab: DetailTab) {
  const groupKeys: Partial<Record<DetailTab, string[]>> = {
    overview: ["order"],
    planning: ["production planning", "production batches"],
    production: ["work orders", "cutting", "printing", "sewing", "quality_checks", "packaging", "bundles", "audit"],
    materials: ["material movements", "material_reservations"],
    packages: ["packages and storage", "finished_goods"],
    finance: ["shipments", "invoices", "payments"],
  };
  const keys = groupKeys[tab] || [];
  return detailedRecordGroups(detail).filter((group) => keys.includes(group.key));
}

function modelLabel(model: ModelRef | null | undefined, fallback: number | string) {
  if (!model) return String(fallback);
  const translated = model.name || model.translations?.en;
  return model.code && translated ? `${model.code} - ${translated}` : model.code || translated || String(fallback);
}

function progressPercent(row: HistoryRow | HistoryDetail) {
  const ordered = Number(row.summary?.ordered_qty || 0);
  if (!ordered) return 0;
  const completed = Math.max(Number(row.summary?.packaged_qty || 0), Number(row.summary?.shipped_qty || 0));
  return Math.min(100, Math.round((completed / ordered) * 100));
}

function StatCard({ label, value, detail, icon: Icon }: { label: string; value: string; detail?: string; icon: any }) {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="label">{label}</div>
          <div className="mt-1 text-2xl font-semibold text-[#14110b]">{value}</div>
        </div>
        <div className="rounded-md border border-[#ecebe3] bg-[#f8f7f3] p-2 text-[#56503f]">
          <Icon className="h-4 w-4" />
        </div>
      </div>
      {detail ? <div className="mt-2 text-xs text-[#8a8472]">{detail}</div> : null}
    </div>
  );
}

export default function OrderHistoryPage() {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [query, setQuery] = useState("");
  const [createdFrom, setCreatedFrom] = useState("");
  const [createdTo, setCreatedTo] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("overview");

  const historyParams = new URLSearchParams({
    include_total: "true",
    page: String(page),
    page_size: String(pageSize),
  });
  if (query.trim()) historyParams.set("q", query.trim());
  if (createdFrom) historyParams.set("created_from", createdFrom);
  if (createdTo) historyParams.set("created_to", createdTo);
  const historyUrl = `/api/sales-orders/history?${historyParams.toString()}`;
  const { data: pageData, isLoading } = useSWR<any>(historyUrl, fetcher);
  const rows = useMemo<HistoryRow[]>(() => pageData?.rows || [], [pageData]);
  const activeKey = selectedKey;
  const activeRow = rows.find((row) => row.history_key === activeKey);
  const detailUrl = activeRow
    ? activeRow.record_type === "production_order"
      ? `/api/sales-orders/history/production/${activeRow.id}`
      : `/api/sales-orders/${activeRow.id}/history`
    : null;
  const { data: detail, isLoading: detailLoading } = useSWR<HistoryDetail>(detailUrl, fetcher);

  useEffect(() => {
    if (!rows.length || !activeKey) {
      setSelectedKey(null);
      return;
    }
    if (!rows.some((row) => row.history_key === activeKey)) {
      setSelectedKey(null);
    }
  }, [rows, activeKey]);

  const totals = useMemo(() => {
    return rows.reduce(
      (acc, row) => {
        acc.orders += 1;
        acc.ordered += Number(row.summary?.ordered_qty || 0);
        acc.packaged += Number(row.summary?.packaged_qty || 0);
        acc.shipped += Number(row.summary?.shipped_qty || 0);
        acc.value += Number(row.total_amount || 0);
        acc.paid += Number(row.summary?.paid_total || 0);
        return acc;
      },
      { orders: 0, ordered: 0, packaged: 0, shipped: 0, value: 0, paid: 0 },
    );
  }, [rows]);

  return (
    <div>
      <PageHeader
        eyebrow={t("page.orderHistory.eyebrow")}
        title={t("page.orderHistory.title")}
        subtitle={t("page.orderHistory.subtitle")}
      />

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
        <StatCard icon={FileText} label={t("page.orderHistory.orders")} value={qty(totals.orders)} detail={t("page.orderHistory.ordersShown")} />
        <StatCard icon={PackageCheck} label={t("page.orderHistory.productFlow")} value={`${qty(totals.packaged)} / ${qty(totals.ordered)}`} detail={t("page.orderHistory.packagedOrdered")} />
        <StatCard icon={Truck} label={t("page.orderHistory.shipped")} value={qty(totals.shipped)} detail={t("page.orderHistory.fromVisibleOrders")} />
        <StatCard icon={WalletCards} label={t("page.orderHistory.paid")} value={money(totals.paid)} detail={t("page.orderHistory.value", { amount: money(totals.value) })} />
      </div>

      <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(280px,1fr)_12rem_12rem]">
        <div>
          <label className="label">{t("common.search")}</label>
          <div className="flex h-9 min-w-[280px] items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3">
            <Search className="h-4 w-4 text-[#8a8472]" />
            <input
              className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
              placeholder={t("page.orderHistory.searchPlaceholder")}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(1);
              }}
            />
            {query ? <button className="icon-btn" onClick={() => setQuery("")} title={t("common.clear")}><X /></button> : null}
          </div>
        </div>
        <label className="block">
          <span className="label">{t("common.createdFrom")}</span>
          <input className="input" type="date" value={createdFrom} onChange={(e) => { setCreatedFrom(e.target.value); setPage(1); }} />
        </label>
        <label className="block">
          <span className="label">{t("common.createdTo")}</span>
          <input className="input" type="date" value={createdTo} onChange={(e) => { setCreatedTo(e.target.value); setPage(1); }} />
        </label>
      </div>

      <div>
        <section className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="table min-w-[1380px]">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("page.planning.planningOrder")}</th>
                  <th>{t("field.modelNo")} / {t("field.variantNo")}</th>
                  <th>{t("field.customer")}</th>
                  <th>{t("field.date")}</th>
                  <th>{t("page.orderHistory.doneAt")}</th>
                  <th className="text-right">{t("page.orderHistory.orderedQty")}</th>
                  <th className="text-right">{t("page.orderHistory.packagedQty")}</th>
                  <th>{t("page.processes.progress")}</th>
                  <th className="text-right">{t("field.total")}</th>
                  <th>{t("common.status")}</th>
                </tr>
              </thead>
              <tbody>
                {isLoading ? <tr><td colSpan={11} className="text-[#8a8472]">{t("common.loading")}</td></tr> : null}
                {!isLoading && rows.length === 0 ? <tr><td colSpan={11} className="text-[#8a8472]">{t("page.orderHistory.empty")}</td></tr> : null}
                {rows.map((row) => {
                  const active = row.history_key === activeKey;
                  const pct = progressPercent(row);
                  const product = row.products?.[0];
                  return (
                    <tr
                      key={row.history_key}
                      className={`${active ? "bg-[#fdf3eb]" : ""} cursor-pointer`}
                      onClick={() => {
                        setSelectedKey(row.history_key);
                        setDetailTab("overview");
                      }}
                    >
                      <td>
                        <button
                          type="button"
                          className="mono font-medium hover:underline"
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedKey(row.history_key);
                            setDetailTab("overview");
                          }}
                        >
                          {row.order_no}
                        </button>
                      </td>
                      <td className="mono">{row.group_order_no || "-"}</td>
                      <td className="min-w-[250px]">
                        {product ? (
                          <div className="flex items-center gap-3">
                            {product.picture_url ? (
                              <Image
                                src={product.picture_url}
                                alt={[product.model_no || product.code, product.variant_no].filter(Boolean).join(" ")}
                                width={44}
                                height={44}
                                unoptimized
                                className="h-11 w-11 shrink-0 rounded-md border border-[#ded9ca] bg-white object-cover"
                              />
                            ) : (
                              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-[#ded9ca] bg-[#f8f7f3] text-xs text-[#8a8472]">—</div>
                            )}
                            <div className="min-w-0">
                              <div className="truncate font-medium text-[#14110b]">{product.model_no || product.code || "-"}</div>
                              <div className="text-xs text-[#56503f]">{t("field.variantNo")}: {product.variant_no || "-"}</div>
                              {product.name ? <div className="truncate text-xs text-[#8a8472]">{product.name}</div> : null}
                              {(row.products?.length || 0) > 1 ? <div className="text-xs text-[#8a8472]">{t("page.orderHistory.moreProducts", { count: (row.products?.length || 1) - 1 })}</div> : null}
                            </div>
                          </div>
                        ) : "-"}
                      </td>
                      <td>{row.record_type === "production_order" ? row.ordered_for || productionTypeLabel(row.order_type, t) : row.customer_name || "-"}</td>
                      <td>{dateOnly(row.created_at)}</td>
                      <td>{dateOnly(row.completed_at)}</td>
                      <td className="mono text-right">{qty(row.summary?.ordered_qty || 0)}</td>
                      <td className="mono text-right">{qty(row.summary?.packaged_qty || 0)}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="mini-bar w-24"><span style={{ width: `${pct}%` }} /></div>
                          <span className="mono text-xs text-[#8a8472]">{pct}%</span>
                        </div>
                      </td>
                      <td className="text-right">{money(row.total_amount)}</td>
                      <td><span className="badge">{statusLabel(row.status, t)}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <PaginationControls
            page={page}
            pageSize={pageSize}
            total={Number(pageData?.total || rows.length)}
            count={rows.length}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </section>

        <Modal
          open={Boolean(activeKey)}
          onClose={() => setSelectedKey(null)}
          title={detail?.order_no || t("page.orderHistory.orderDetails")}
          full
        >
          {detailLoading || !detail ? (
            <div className="py-10 text-center text-sm text-[#8a8472]">{t("common.loading")}</div>
          ) : (
            <div className="space-y-4">
              <nav className="sticky top-0 z-10 -mx-6 flex gap-1 overflow-x-auto border-y border-[#ecebe3] bg-[var(--erp-surface)] px-6" aria-label={t("page.orderHistory.detailSections")}>
                {([
                  ["overview", t("page.orderHistory.tabOverview")],
                  ["planning", t("page.orderHistory.tabPlanning")],
                  ["production", t("page.orderHistory.tabProduction")],
                  ["materials", t("page.orderHistory.tabMaterials")],
                  ["packages", t("page.orderHistory.tabPackages")],
                  ["finance", t("page.orderHistory.tabFinance")],
                  ["timeline", t("page.orderHistory.tabTimeline")],
                ] as [DetailTab, string][]).map(([tab, label]) => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setDetailTab(tab)}
                    className={`whitespace-nowrap border-b-2 px-3 py-3 text-sm ${detailTab === tab ? "border-[#14110b] font-semibold text-[#14110b]" : "border-transparent text-[#6f684f] hover:text-[#14110b]"}`}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              {detailTab === "overview" ? (
                <>
              <section className="card p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <Link
                      href={detail.record_type === "production_order" ? `/production-orders/${detail.id}` : `/sales-orders/${detail.id}`}
                      className="mono text-lg font-semibold hover:underline"
                    >
                      {detail.order_no}
                    </Link>
                    <div className="mt-1 text-sm text-[#56503f]">
                      {detail.record_type === "production_order"
                        ? [detail.group_order_no, detail.ordered_for, productionTypeLabel(detail.order_type, t)].filter(Boolean).join(" · ")
                        : `${detail.customer_name || "-"} · ${productionTypeLabel(detail.order_type, t)}`}
                    </div>
                  </div>
                  <span className="badge">{statusLabel(detail.status, t)}</span>
                </div>
                <dl className="mt-4 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
                  <div className="rounded-md bg-[#f8f7f3] p-3"><dt className="label">{t("page.orderHistory.orderedAt")}</dt><dd>{dateTime(detail.created_at)}</dd></div>
                  <div className="rounded-md bg-[#f8f7f3] p-3"><dt className="label">{t("page.orderHistory.doneAt")}</dt><dd>{dateTime(detail.completed_at)}</dd></div>
                  <div className="rounded-md bg-[#f8f7f3] p-3"><dt className="label">{t("field.deadline")}</dt><dd>{dateOnly(detail.deadline)}</dd></div>
                  <div className="rounded-md bg-[#f8f7f3] p-3"><dt className="label">{t("page.orderHistory.lastActivity")}</dt><dd>{dateTime(detail.last_activity_at)}</dd></div>
                </dl>
              </section>

              <section className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <StatCard icon={PackageCheck} label={t("page.orderHistory.orderedQty")} value={qty(detail.summary.ordered_qty)} detail={t("page.orderHistory.plannedQty", { qty: qty(detail.summary.planned_qty) })} />
                <StatCard icon={Truck} label={t("page.orderHistory.shipped")} value={qty(detail.summary.shipped_qty)} detail={t("page.orderHistory.packagesShipments", { packages: detail.summary.package_count, shipments: detail.summary.shipment_count })} />
                <StatCard icon={WalletCards} label={t("page.orderHistory.money")} value={money(detail.summary.order_amount)} detail={t("page.orderHistory.paidOutstanding", { paid: money(detail.summary.paid_total), open: money(detail.summary.outstanding_amount) })} />
                <StatCard icon={CalendarCheck} label={t("page.orderHistory.materialSpend")} value={money(detail.summary.material_spent_cost)} detail={t("page.orderHistory.materialLines", { count: detail.materials.spent.length })} />
              </section>

              <section className="card overflow-x-auto">
                <div className="border-b border-[#ecebe3] px-4 py-3">
                  <h2 className="app-card-title">{t("page.soDetail.items")}</h2>
                </div>
                <table className="table min-w-[640px]">
                  <thead>
                    <tr>
                      <th>{t("field.model")}</th>
                      <th>{t("field.color")}</th>
                      <th>{t("field.size")}</th>
                      <th className="text-right">{t("field.qty")}</th>
                      <th className="text-right">{t("field.total")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.items.map((item) => (
                      <tr key={item.id}>
                        <td>{modelLabel(item.model, item.model_id)}</td>
                        <td>{item.color}</td>
                        <td>{item.size}</td>
                        <td className="text-right">{qty(item.quantity)}</td>
                        <td className="text-right">{money(item.line_total)}</td>
                      </tr>
                    ))}
                    {detail.items.length === 0 ? <tr><td colSpan={5} className="text-[#8a8472]">{t("page.orderHistory.noRows")}</td></tr> : null}
                  </tbody>
                </table>
              </section>
              <section className="card overflow-hidden">
                {recordGroupsForTab(detail, "overview").map((group) => (
                  <LedgerRecordGroup key={group.key} title={readableField(group.key)} rows={group.rows} />
                ))}
              </section>
                </>
              ) : null}

              {detailTab === "planning" ? (
                <section className="card overflow-hidden">
                  {recordGroupsForTab(detail, "planning").map((group) => (
                    <LedgerRecordGroup key={group.key} title={readableField(group.key)} rows={group.rows} />
                  ))}
                  {recordGroupsForTab(detail, "planning").length === 0 ? <div className="p-4 text-sm text-[#8a8472]">{t("page.orderHistory.noRows")}</div> : null}
                </section>
              ) : null}

              {detailTab === "materials" ? (
                <div className="space-y-4">
              <section className="card overflow-x-auto">
                <div className="border-b border-[#ecebe3] px-4 py-3">
                  <h2 className="app-card-title">{t("page.orderHistory.materialSpend")}</h2>
                </div>
                <table className="table min-w-[640px]">
                  <thead>
                    <tr>
                      <th>{t("field.item")}</th>
                      <th>{t("field.category")}</th>
                      <th className="text-right">{t("field.qty")}</th>
                      <th className="text-right">{t("page.orderHistory.estimatedCost")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.materials.spent.map((row) => (
                      <tr key={`${row.item_id}-${row.unit}`}>
                        <td><span className="mono">{row.sku}</span> - {row.name}</td>
                        <td>{row.category}</td>
                        <td className="text-right">{qty(row.quantity, row.unit)}</td>
                        <td className="text-right">{money(row.estimated_cost)}</td>
                      </tr>
                    ))}
                    {detail.materials.spent.length === 0 ? <tr><td colSpan={4} className="text-[#8a8472]">{t("page.orderHistory.noRows")}</td></tr> : null}
                  </tbody>
                </table>
              </section>
                  <section className="card overflow-hidden">
                    {recordGroupsForTab(detail, "materials").map((group) => (
                      <LedgerRecordGroup key={group.key} title={readableField(group.key)} rows={group.rows} />
                    ))}
                  </section>
                </div>
              ) : null}

              {detailTab === "production" ? (
                <div className="space-y-4">
              <section className="card overflow-x-auto">
                <div className="border-b border-[#ecebe3] px-4 py-3">
                  <h2 className="app-card-title">{t("page.orderHistory.production")}</h2>
                </div>
                <table className="table min-w-[760px]">
                  <thead>
                    <tr>
                      <th>{t("field.orderNo")}</th>
                      <th>{t("field.operation")}</th>
                      <th className="text-right">{t("field.passed")}</th>
                      <th className="text-right">{t("field.failed")}</th>
                      <th>{t("common.status")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.production_orders.flatMap((po) =>
                      po.work_orders.map((wo) => (
                        <tr key={`${po.id}-${wo.id}`}>
                          <td><Link className="mono hover:underline" href={`/production-orders/${po.id}`}>{orderReference(po, po.production_no)}</Link></td>
                          <td>{wo.operation}</td>
                          <td className="text-right">{qty(wo.passed_qty || wo.actual_output_qty)}</td>
                          <td className="text-right">{qty(wo.failed_qty)}</td>
                          <td><span className="badge">{statusLabel(wo.status, t)}</span></td>
                        </tr>
                      )),
                    )}
                    {detail.production_orders.length === 0 ? <tr><td colSpan={5} className="text-[#8a8472]">{t("page.orderHistory.noRows")}</td></tr> : null}
                  </tbody>
                </table>
              </section>
                  <section className="card overflow-hidden">
                    {recordGroupsForTab(detail, "production").map((group) => (
                      <LedgerRecordGroup key={group.key} title={readableField(group.key)} rows={group.rows} />
                    ))}
                  </section>
                </div>
              ) : null}

              {detailTab === "packages" ? (
                <div className="space-y-4">
              <section className="card overflow-x-auto">
                <div className="border-b border-[#ecebe3] px-4 py-3">
                  <h2 className="app-card-title">{t("page.orderHistory.packagesShipmentsTitle")}</h2>
                </div>
                <table className="table min-w-[720px]">
                  <thead>
                    <tr>
                      <th>{t("field.packageNo")}</th>
                      <th className="text-right">{t("field.qty")}</th>
                      <th>{t("common.status")}</th>
                      <th>{t("page.orderHistory.packedAt")}</th>
                      <th>{t("page.orderHistory.shippedAt")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.packages.map((pkg) => (
                      <tr key={pkg.id}>
                        <td><Link className="mono hover:underline" href={`/packages/${pkg.id}`}>{pkg.package_no}</Link></td>
                        <td className="text-right">{qty(pkg.total_quantity)}</td>
                        <td><span className="badge">{statusLabel(pkg.status, t)}</span></td>
                        <td>{dateTime(pkg.packed_at)}</td>
                        <td>{dateTime(pkg.shipped_at)}</td>
                      </tr>
                    ))}
                    {detail.packages.length === 0 ? <tr><td colSpan={5} className="text-[#8a8472]">{t("page.orderHistory.noRows")}</td></tr> : null}
                  </tbody>
                </table>
              </section>
                  <section className="card overflow-hidden">
                    {recordGroupsForTab(detail, "packages").map((group) => (
                      <LedgerRecordGroup key={group.key} title={readableField(group.key)} rows={group.rows} />
                    ))}
                  </section>
                </div>
              ) : null}

              {detailTab === "finance" ? (
                <div className="space-y-4">
              <section className="card overflow-x-auto">
                <div className="border-b border-[#ecebe3] px-4 py-3">
                  <h2 className="app-card-title">{t("page.orderHistory.finance")}</h2>
                </div>
                <table className="table min-w-[680px]">
                  <thead>
                    <tr>
                      <th>{t("field.invoice")}</th>
                      <th className="text-right">{t("field.amount")}</th>
                      <th>{t("common.status")}</th>
                      <th>{t("field.payment")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.invoices.map((invoice) => {
                      const paid = detail.payments.filter((payment) => payment.invoice_id === invoice.id).reduce((sum, payment) => sum + Number(payment.amount || 0), 0);
                      return (
                        <tr key={invoice.id}>
                          <td className="mono">{invoice.invoice_no}</td>
                          <td className="text-right">{money(invoice.amount)}</td>
                          <td><span className="badge">{statusLabel(invoice.status, t)}</span></td>
                          <td>{money(paid)}</td>
                        </tr>
                      );
                    })}
                    {detail.invoices.length === 0 ? <tr><td colSpan={4} className="text-[#8a8472]">{t("page.orderHistory.noRows")}</td></tr> : null}
                  </tbody>
                </table>
              </section>
                  <section className="card overflow-hidden">
                    {recordGroupsForTab(detail, "finance").map((group) => (
                      <LedgerRecordGroup key={group.key} title={readableField(group.key)} rows={group.rows} />
                    ))}
                  </section>
                </div>
              ) : null}

              {detailTab === "timeline" ? (
              <section className="card">
                <div className="border-b border-[#ecebe3] px-4 py-3">
                  <h2 className="app-card-title">{t("page.orderHistory.timeline")}</h2>
                </div>
                <div className="divide-y divide-[#ecebe3]">
                  {detail.timeline.map((event, idx) => (
                    <div key={`${event.type}-${event.at}-${idx}`} className="flex gap-3 px-4 py-3 text-sm">
                      <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-[#8a8472]" />
                      <div className="min-w-0">
                        <div className="font-medium text-[#14110b]">{event.title}</div>
                        <div className="text-xs text-[#8a8472]">{dateTime(event.at)}</div>
                      </div>
                    </div>
                  ))}
                  {detail.timeline.length === 0 ? <div className="p-4 text-sm text-[#8a8472]">{t("page.orderHistory.noRows")}</div> : null}
                </div>
              </section>
              ) : null}
            </div>
          )}
        </Modal>
      </div>
    </div>
  );
}
