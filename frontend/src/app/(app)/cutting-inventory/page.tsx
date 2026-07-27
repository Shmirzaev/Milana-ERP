"use client";

import Link from "next/link";
import { Fragment, useMemo, useState, type FormEvent } from "react";
import { ChevronDown, ChevronRight, QrCode, RefreshCw, Search, X } from "lucide-react";
import useSWR from "swr";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import FabricThumbnail from "@/components/FabricThumbnail";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";
import { statusLabel } from "@/components/StagePipeline";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";

type Department = { id: number; name: string; code: string };

type BundleRow = {
  id: number;
  bundle_no: string;
  barcode: string;
  production_order_id: number;
  production_no?: string | null;
  order_no?: string | null;
  production_batch_id?: number | null;
  batch_label?: string | null;
  tracking_passport_no?: string | null;
  model_id: number;
  model_code?: string | null;
  material_image_url?: string | null;
  color: string;
  size: string;
  quantity: number;
  status: string;
  next_department_id?: number | null;
  sewing_factory_code?: string | null;
};

type InventoryResponse = {
  rows: BundleRow[];
  total: number;
  total_quantity: number;
  total_orders: number;
  page: number;
  page_size: number;
};

type Group = {
  key: string;
  orderNo: string;
  batchLabel: string;
  trackingPassportNo: string;
  productionBatchId: number | null;
  items: BundleRow[];
  totalQty: number;
  toPrinting: number;
  toSewing: number;
};

const SEWING_CODES = new Set(["SEW", "MIL", "BST", "ECO"]);

function nextDepartmentCode(row: BundleRow, departmentById: Map<number, Department>) {
  const dept = row.next_department_id ? departmentById.get(Number(row.next_department_id)) : null;
  return String(dept?.code || "").toUpperCase();
}

function factoryLabel(value: string | null | undefined, t: (key: string) => string) {
  const normalized = String(value || "").trim().toUpperCase();
  if (normalized === "BST" || normalized === "BESTTEX") return t("factory.besttex");
  if (normalized === "ECO" || normalized === "ECO COTTON" || normalized === "ECO_COTTON") return t("factory.ecoCotton");
  return t("factory.milana");
}

function destinationLabel(row: BundleRow, departmentById: Map<number, Department>, t: (key: string) => string) {
  const code = nextDepartmentCode(row, departmentById);
  if (row.status === "sent_to_printing" || code === "PRT") return t("dash.printing");
  if (row.status === "sent_to_sewing" || SEWING_CODES.has(code)) return factoryLabel(row.sewing_factory_code || code, t);
  return t("page.cuttingInventory.nextScan");
}

function inventoryState(row: BundleRow, t: (key: string) => string) {
  if (row.status === "sent_to_printing") return t("page.cuttingInventory.waitingPrintingReceive");
  if (row.status === "sent_to_sewing") return t("page.cuttingInventory.waitingSewingReceive");
  return t("page.cuttingInventory.readyForNextScan");
}

export default function CuttingInventoryPage() {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const { data: departments = [] } = useSWR<Department[]>("/api/departments", fetcher);
  const departmentById = useMemo(() => new Map(departments.map((d) => [Number(d.id), d])), [departments]);

  const inventoryUrl = useMemo(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (search) params.set("q", search);
    return `/api/bundles/cutting-inventory?${params.toString()}`;
  }, [page, pageSize, search]);

  const { data: pageData, mutate, isLoading } = useSWR<InventoryResponse>(
    inventoryUrl,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const rows = useMemo(() => pageData?.rows || [], [pageData?.rows]);

  const grouped = useMemo<Group[]>(() => {
    const map = new Map<string, Group>();
    for (const row of rows) {
      const orderNo = orderReference(row, `#${row.production_order_id}`);
      const productionBatchId = row.production_batch_id ? Number(row.production_batch_id) : null;
      const batchLabel = row.batch_label || (productionBatchId ? `${t("field.batch")} #${productionBatchId}` : "-");
      const trackingPassportNo = row.tracking_passport_no || "";
      const key = `${orderNo}::${productionBatchId || "none"}`;
      const code = nextDepartmentCode(row, departmentById);
      const goesToPrinting = row.status === "sent_to_printing" || code === "PRT";
      const group = map.get(key);
      if (group) {
        group.items.push(row);
        group.totalQty += Number(row.quantity || 0);
        if (goesToPrinting) group.toPrinting += 1;
        else group.toSewing += 1;
      } else {
        map.set(key, {
          key,
          orderNo,
          productionBatchId,
          batchLabel,
          trackingPassportNo,
          items: [row],
          totalQty: Number(row.quantity || 0),
          toPrinting: goesToPrinting ? 1 : 0,
          toSewing: goesToPrinting ? 0 : 1,
        });
      }
    }
    return Array.from(map.values());
  }, [departmentById, rows, t]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchDraft.trim());
    setPage(1);
  }

  function clearSearch() {
    setSearchDraft("");
    setSearch("");
    setPage(1);
  }

  function toggleGroup(key: string) {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function printGroupLabels(group: Group) {
    if (group.productionBatchId) {
      api.openLabel(`/api/bundles/label-sheet/by-batch/${group.productionBatchId}`);
      return;
    }
    const ids = group.items.map((item) => item.id).filter(Boolean).join(",");
    if (ids) api.openLabel(`/api/bundles/label-sheet/by-ids?ids=${encodeURIComponent(ids)}`);
  }

  const totalBundles = Number(pageData?.total || 0);
  const totalQuantity = Number(pageData?.total_quantity || 0);
  const totalOrders = Number(pageData?.total_orders || 0);

  return (
    <div>
      <PageHeader
        title={t("page.cuttingInventory.title")}
        subtitle={t("page.cuttingInventory.subtitle")}
        actions={(
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn" onClick={() => mutate()}>
              <RefreshCw className="h-4 w-4" />
              {t("btn.refresh")}
            </button>
            <Link href="/bundles/scan/cutting" className="btn btn-primary">
              <QrCode className="h-4 w-4" />
              {t("btn.scan")}
            </Link>
          </div>
        )}
      />

      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <div className="card p-4">
          <div className="text-sm text-slate-500">{t("page.cuttingInventory.orders")}</div>
          <div className="mt-1 text-2xl font-semibold text-slate-900">{totalOrders.toLocaleString()}</div>
        </div>
        <div className="card p-4">
          <div className="text-sm text-slate-500">{t("page.cuttingInventory.bundles")}</div>
          <div className="mt-1 text-2xl font-semibold text-slate-900">{totalBundles.toLocaleString()}</div>
        </div>
        <div className="card p-4">
          <div className="text-sm text-slate-500">{t("page.cuttingInventory.pieces")}</div>
          <div className="mt-1 text-2xl font-semibold text-slate-900">{totalQuantity.toLocaleString()}</div>
        </div>
      </div>

      <div className="card">
        <div className="border-b border-[#e3dfd3] p-4">
          <form className="flex flex-col gap-2 sm:flex-row" onSubmit={submitSearch}>
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className="input pl-9"
                value={searchDraft}
                onChange={(event) => setSearchDraft(event.target.value)}
                placeholder={t("page.cuttingInventory.searchPlaceholder")}
              />
            </div>
            <button type="submit" className="btn btn-primary">{t("common.search")}</button>
            {search && (
              <button type="button" className="btn" onClick={clearSearch}>
                <X className="h-4 w-4" />
                {t("common.clear")}
              </button>
            )}
          </form>
        </div>

        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.orderNo")}</th>
                <th>{t("field.batch")}</th>
                <th>{t("field.model")} / {t("nav.bundles")}</th>
                <th>{t("field.qty")}</th>
                <th>{t("field.next")}</th>
                <th>{t("common.status")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-slate-500">{t("common.loading")}</td>
                </tr>
              )}
              {!isLoading && grouped.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-slate-500">{t("page.cuttingInventory.empty")}</td>
                </tr>
              )}
              {grouped.map((group) => {
                const isOpen = openGroups.has(group.key);
                return (
                  <Fragment key={group.key}>
                    <tr className="bg-[#f8f6ef]">
                      <td className="font-semibold">
                        <button
                          type="button"
                          className="inline-flex min-w-0 items-center gap-2 text-left"
                          onClick={() => toggleGroup(group.key)}
                          aria-expanded={isOpen}
                        >
                          {isOpen ? <ChevronDown className="h-4 w-4 shrink-0" /> : <ChevronRight className="h-4 w-4 shrink-0" />}
                          <span className="truncate">{group.orderNo}</span>
                        </button>
                      </td>
                      <td>
                        <div>{group.batchLabel}</div>
                        {group.trackingPassportNo && <div className="text-xs text-slate-500">{group.trackingPassportNo}</div>}
                      </td>
                      <td>
                        <div className="flex min-w-[190px] items-center gap-3">
                          <FabricThumbnail
                            imageUrl={group.items[0]?.material_image_url}
                            label={group.items[0]?.model_code}
                          />
                          <div className="min-w-0">
                            <div className="truncate font-medium">{group.items[0]?.model_code || group.items[0]?.model_id || "-"}</div>
                            <div className="text-xs text-slate-500">{group.items.length} {t("nav.bundles")}</div>
                          </div>
                        </div>
                      </td>
                      <td>{group.totalQty}</td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          {group.toPrinting > 0 && <span className="badge">{t("page.cuttingInventory.toPrinting")}: {group.toPrinting}</span>}
                          {group.toSewing > 0 && <span className="badge">{t("page.cuttingInventory.toSewing")}: {group.toSewing}</span>}
                        </div>
                      </td>
                      <td>{t("page.cuttingInventory.waitingForReceive")}</td>
                      <td>
                        <button type="button" className="text-brand-600 hover:underline" onClick={() => printGroupLabels(group)}>
                          {t("page.packaging.printAllLabels")}
                        </button>
                      </td>
                    </tr>
                    {isOpen && group.items.map((row) => (
                      <tr key={row.id}>
                        <td className="pl-10">
                          <Link className="font-medium text-brand-600 hover:underline" href={`/bundles/${row.id}`}>
                            {row.bundle_no}
                          </Link>
                          <div><code>{row.barcode}</code></div>
                        </td>
                        <td>
                          <div>{row.batch_label || "-"}</div>
                          {row.tracking_passport_no && <div className="text-xs text-slate-500">{row.tracking_passport_no}</div>}
                        </td>
                        <td>
                          <div className="flex items-center gap-2">
                            <FabricThumbnail imageUrl={row.material_image_url} label={row.model_code} size="sm" />
                            <span>{row.model_code || row.model_id}</span>
                          </div>
                        </td>
                        <td>{row.quantity}</td>
                        <td>{destinationLabel(row, departmentById, t)}</td>
                        <td>
                          <div className="flex flex-col gap-1">
                            <span className="badge w-fit">{statusLabel(row.status, t)}</span>
                            <span className="text-xs text-slate-500">{inventoryState(row, t)}</span>
                          </div>
                        </td>
                        <td>
                          <button type="button" className="text-slate-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${row.id}/label`)}>
                            {t("btn.label")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>

        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={totalBundles}
          count={rows.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </div>
    </div>
  );
}
