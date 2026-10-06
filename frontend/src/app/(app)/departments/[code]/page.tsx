"use client";
import { formatVariantNumber } from "@/lib/variantDisplay";
import { localizeError } from "@/lib/errorMessages";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import { Fragment, useDeferredValue, useEffect, useMemo, useState } from "react";
import useSWRInfinite from "swr/infinite";

import ImageThumbnail from "@/components/ImageThumbnail";
import ReturnPackages from "@/components/ReturnPackages";
import PageHeader from "@/components/PageHeader";
import StocktakeLink from "@/components/StocktakeLink";
import CuttingOrderList from "@/components/CuttingOrderList";
import DepartmentOrderList from "@/components/DepartmentOrderList";
import ShipmentItemLines from "@/components/ShipmentItemLines";
import { statusLabel } from "@/components/StagePipeline";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { orderReference } from "@/lib/orderRef";

const DEPT_LABELS: Record<string, string> = {
  CUT: "nav.cuttingFloor",
  ECT: "nav.ecoCottonCutting",
  PRT: "nav.printingFloor",
  SEW: "nav.sewingFloor",
  MIL: "nav.milanaSewing",
  BST: "nav.besttexSewing",
  ECO: "nav.ecoCottonSewing",
  PKG: "nav.packagingFloor",
  BPK: "nav.besttexPackaging",
  ECP: "nav.ecoCottonPackaging",
  FGS: "nav.finishedGoods",
};

type InboxPackagePage = {
  rows: any[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  group_total: number;
};

type InboxAwaitingPackagingPage = {
  rows: any[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

type DepartmentOrderPage = {
  rows: any[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
};

type CuttingOrderPage = DepartmentOrderPage;

function MaterialThumb({ row }: { row: any }) {
  const imageUrl = row?.material_image_url || row?.model_image_url;
  const src = storageThumbnailUrl(imageUrl, 160);
  if (!src) return null;
  const label = row?.material_item_name || row?.material_item_sku || row?.model_name || row?.model_no || row?.model_code || "Material";
  return (
    <a href={imagePreviewHref(imageUrl, label)} target="_blank" rel="noreferrer" className="h-12 w-12 shrink-0 overflow-hidden rounded-md border border-[#ecebe3] bg-[#f8f7f3]">
      <img src={src} alt={label} className="h-full w-full object-cover" loading="lazy" />
    </a>
  );
}

function materialLine(row: any) {
  const name = String(row?.material_item_name || "").trim();
  const sku = String(row?.material_item_sku || "").trim();
  const label = [sku, name].filter(Boolean).join(" - ");
  if (!label) return null;
  return <div className="break-words text-[11px] text-slate-500">{label}</div>;
}

function orderContextLine(row: any, t: (key: string, vars?: Record<string, string | number>) => string) {
  const modelNo = String(row?.model_no || "").trim();
  const variantNo = formatVariantNumber(row?.variant_no);
  const size = String(row?.size_summary || row?.size || "").trim();
  const parts = [
    modelNo ? { label: t("field.modelNo"), value: modelNo } : null,
    variantNo ? { label: t("field.variantNo"), value: variantNo } : null,
    size ? { label: t("field.size"), value: size } : null,
  ].filter(Boolean) as { label: string; value: string }[];

  if (parts.length === 0) return null;

  return (
    <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] leading-4 text-[#56503f]">
      {parts.map((part) => (
        <span key={part.label} className="min-w-0 max-w-full">
          <span className="text-[#8a8472]">{part.label}:</span> {part.value}
        </span>
      ))}
    </div>
  );
}

export default function DepartmentInboxPage() {
  const { t } = useT();
  const params = useParams<{ code: string }>();
  const router = useRouter();
  const code = String(params.code || "").toUpperCase();
  const isCuttingDepartment = code === "CUT" || code === "ECT";
  const isPackagingDepartment = code === "PKG" || code === "BPK" || code === "ECP";
  const deptLabel = DEPT_LABELS[code] ? t(DEPT_LABELS[code]) : code;
  const [clientTz, setClientTz] = useState("UTC");
  const [creatingShipmentFor, setCreatingShipmentFor] = useState<string | null>(null);
  const [shipmentError, setShipmentError] = useState("");
  const [departmentSearch, setDepartmentSearch] = useState("");
  const deferredDepartmentSearch = useDeferredValue(departmentSearch.trim());
  const [cuttingSearch, setCuttingSearch] = useState("");
  const deferredCuttingSearch = useDeferredValue(cuttingSearch.trim());
  const [pendingPackageSearch, setPendingPackageSearch] = useState("");
  const [readyPackageSearch, setReadyPackageSearch] = useState("");
  const deferredPendingPackageSearch = useDeferredValue(pendingPackageSearch.trim());
  const deferredReadyPackageSearch = useDeferredValue(readyPackageSearch.trim());

  useEffect(() => { setCuttingSearch(""); setDepartmentSearch(""); }, [code]);

  useEffect(() => {
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (tz) setClientTz(tz);
    } catch {
      setClientTz("UTC");
    }
  }, []);

  const inboxUrl = code
    ? `/api/inbox?dept=${code}&tz=${encodeURIComponent(clientTz)}${isPackagingDepartment ? "&include_awaiting_packaging=false" : ""}${code === "FGS" ? "&ready_to_ship_limit=50&ready_to_ship_offset=0" : ""}&include_core_orders=false&ready_to_ship_q=${encodeURIComponent(deferredDepartmentSearch)}`
    : null;
  const { data, isLoading, mutate } = useSWR<any>(inboxUrl, fetcher, { refreshInterval: 10_000 });
  const {
    data: readyToShipPages,
    mutate: mutateReadyToShipPages,
    size: readyToShipSize,
    setSize: setReadyToShipSize,
    isValidating: readyToShipValidating,
  } = useSWRInfinite<any>(
    (index, previous) => {
      if (code !== "FGS") return null;
      if (index === 0) return inboxUrl;
      if (previous && index * 50 >= Number(previous.ready_to_ship_total ?? 0)) return null;
      return `/api/inbox?dept=${code}&tz=${encodeURIComponent(clientTz)}&ready_to_ship_limit=50&ready_to_ship_offset=${index * 50}&include_core_orders=false&ready_to_ship_q=${encodeURIComponent(deferredDepartmentSearch)}`;
    },
    fetcher,
    { refreshInterval: 10_000 },
  );
  const {
    data: departmentOrderPages,
    mutate: mutateDepartmentOrderPages,
    setSize: setDepartmentOrderPageCount,
    isValidating: departmentOrdersValidating,
    isLoading: departmentOrdersLoading,
    error: departmentOrdersError,
  } = useSWRInfinite<DepartmentOrderPage>(
    (index, previous) => code && !isCuttingDepartment && !(previous && !previous.has_more)
      ? `/api/inbox/department-orders?dept=${code}&tz=${encodeURIComponent(clientTz)}&limit=50&offset=${index * 50}&q=${encodeURIComponent(deferredDepartmentSearch)}`
      : null,
    fetcher,
    { refreshInterval: 10_000 },
  );
  const {
    data: cuttingOrderPages,
    mutate: mutateCuttingOrderPages,
    setSize: setCuttingOrderPageCount,
    isValidating: cuttingOrdersValidating,
    isLoading: cuttingOrdersLoading,
    error: cuttingOrdersError,
  } = useSWRInfinite<CuttingOrderPage>(
    (index, previous) => isCuttingDepartment && !(previous && !previous.has_more)
      ? `/api/inbox/cutting-orders?dept=${code}&limit=50&offset=${index * 50}&q=${encodeURIComponent(deferredCuttingSearch)}`
      : null,
    fetcher,
    { refreshInterval: 10_000 },
  );
  const {
    data: pendingPackagePages,
    mutate: mutatePendingPackagePages,
    setSize: setPendingPackagePageCount,
    isValidating: pendingPackagesValidating,
  } = useSWRInfinite<InboxPackagePage>(
    (index, previous) => code === "FGS" && !(previous && !previous.has_more)
      ? `/api/inbox/packages?status=pending&page=${index + 1}&page_size=50&q=${encodeURIComponent([deferredDepartmentSearch, deferredPendingPackageSearch].filter(Boolean).join(" "))}`
      : null,
    fetcher,
  );
  const {
    data: readyPackagePages,
    mutate: mutateReadyPackagePages,
    setSize: setReadyPackagePageCount,
    isValidating: readyPackagesValidating,
  } = useSWRInfinite<InboxPackagePage>(
    (index, previous) => code === "FGS" && !(previous && !previous.has_more)
      ? `/api/inbox/packages?status=ready&page=${index + 1}&page_size=50&q=${encodeURIComponent([deferredDepartmentSearch, deferredReadyPackageSearch].filter(Boolean).join(" "))}`
      : null,
    fetcher,
  );
  const {
    data: awaitingPackagingPages,
    mutate: mutateAwaitingPackagingPages,
    isLoading: awaitingPackagingLoading,
    error: awaitingPackagingError,
    setSize: setAwaitingPackagingPageCount,
    isValidating: awaitingPackagingValidating,
  } = useSWRInfinite<InboxAwaitingPackagingPage>(
    (index, previous) => isPackagingDepartment && !(previous && !previous.has_more)
      ? `/api/inbox/awaiting-packaging?dept=${code}&page=${index + 1}&page_size=50&q=${encodeURIComponent(deferredDepartmentSearch)}`
      : null,
    fetcher,
    { refreshInterval: 10_000 },
  );
  const cuttingWorkOrders = useMemo(
    () => cuttingOrderPages?.flatMap((page) => page.rows) || [],
    [cuttingOrderPages],
  );
  const cuttingOrdersTotal = cuttingOrderPages?.[0]?.total ?? 0;
  const cuttingOrdersHasMore = cuttingOrderPages?.at(-1)?.has_more ?? false;
  const departmentOrders = useMemo(
    () => departmentOrderPages?.flatMap((page) => page.rows.map((row) => ({ ...row, queueKind: row.queue_kind }))) || [],
    [departmentOrderPages],
  );
  const departmentOrdersTotal = departmentOrderPages?.[0]?.total ?? 0;
  const departmentOrdersHasMore = departmentOrderPages?.[departmentOrderPages.length - 1]?.has_more ?? false;
  const pendingPackages = useMemo(() => pendingPackagePages?.flatMap((page) => page.rows) || [], [pendingPackagePages]);
  const readyPackages = useMemo(() => readyPackagePages?.flatMap((page) => page.rows) || [], [readyPackagePages]);
  const awaitingPackagingRows = useMemo(
    () => awaitingPackagingPages?.flatMap((page) => page.rows) || [],
    [awaitingPackagingPages],
  );
  const awaitingPackagingTotal = awaitingPackagingPages?.[0]?.total ?? 0;
  const awaitingPackagingHasMore = awaitingPackagingPages?.[awaitingPackagingPages.length - 1]?.has_more ?? false;
  const pendingPackagesTotal = pendingPackagePages?.[0]?.total ?? 0;
  const readyPackagesTotal = readyPackagePages?.[0]?.total ?? 0;
  const [expandedPackageGroups, setExpandedPackageGroups] = useState<Record<string, boolean>>({});

  const pendingPackagesByOrder = useMemo(() => {
    const groups = new Map<string, { key: string; sales_order_id: number | null; order_no: string | null; sales_order_no: string | null; packages: any[]; total_quantity: number }>();
    for (const p of pendingPackages) {
      const key = p.sales_order_id == null ? `po-${p.production_order_id || p.id}` : `so-${p.sales_order_id}`;
      const existing = groups.get(key) ?? {
        key,
        sales_order_id: p.sales_order_id == null ? null : Number(p.sales_order_id),
        order_no: p.order_no || p.sales_order_no || p.production_no || null,
        sales_order_no: p.sales_order_no || p.order_no || null,
        packages: [],
        total_quantity: 0,
      };
      existing.order_no = existing.order_no || p.order_no || p.sales_order_no || null;
      existing.sales_order_no = existing.sales_order_no || p.sales_order_no || p.order_no || null;
      existing.packages.push(p);
      existing.total_quantity += Number(p.total_quantity || 0);
      groups.set(key, existing);
    }
    return Array.from(groups.values())
      .map((g) => ({
        ...g,
        packages: [...g.packages].sort((a, b) => String(b.package_no || "").localeCompare(String(a.package_no || ""))),
      }))
      .sort((a, b) => {
        const left = a.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        const right = b.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        return left - right;
      });
  }, [pendingPackages]);
  const readyPackagesByOrder = useMemo(() => {
    const groups = new Map<string, { key: string; sales_order_id: number | null; order_no: string | null; sales_order_no: string | null; packages: any[]; total_quantity: number }>();
    for (const p of readyPackages) {
      const key = p.sales_order_id == null ? "no-so" : `so-${p.sales_order_id}`;
      const existing = groups.get(key) ?? {
        key,
        sales_order_id: p.sales_order_id == null ? null : Number(p.sales_order_id),
        order_no: p.order_no || p.sales_order_no || null,
        sales_order_no: p.sales_order_no || p.order_no || null,
        packages: [],
        total_quantity: 0,
      };
      existing.order_no = existing.order_no || p.order_no || p.sales_order_no || null;
      existing.sales_order_no = existing.sales_order_no || p.sales_order_no || p.order_no || null;
      existing.packages.push(p);
      existing.total_quantity += Number(p.total_quantity || 0);
      groups.set(key, existing);
    }
    return Array.from(groups.values())
      .map((g) => ({
        ...g,
        packages: [...g.packages].sort((a, b) => String(b.package_no || "").localeCompare(String(a.package_no || ""))),
      }))
      .sort((a, b) => {
        const left = a.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        const right = b.sales_order_id ?? Number.MAX_SAFE_INTEGER;
        return left - right;
      });
  }, [readyPackages]);
  const readyToShipRows = useMemo(
    () => readyToShipPages?.flatMap((page) => page?.ready_to_ship ?? [])
      ?? (Array.isArray(data?.ready_to_ship) ? data.ready_to_ship : []),
    [data?.ready_to_ship, readyToShipPages],
  );
  const readyToShipTotal = Number(readyToShipPages?.[0]?.ready_to_ship_total ?? data?.ready_to_ship_total ?? 0);
  const hasReadyToShipOrders = readyToShipRows.length > 0;
  const readyToShipHasMore = code === "FGS" && readyToShipRows.length < readyToShipTotal;
  const readyToShipOrders = useMemo(() => {
    if (readyToShipRows.length > 0) {
      return readyToShipRows;
    }
    return readyPackagesByOrder.map((g) => ({
      sales_order_id: g.sales_order_id,
      order_no: g.order_no,
      sales_order_no: g.sales_order_no,
      order_type: "standard",
      shipment_type: "standard",
      customer_name: null,
      customer_address: null,
      destination: null,
      shipment_id: null,
      shipment_no: null,
      shipment_status: "not_created",
      packages: g.packages.length,
      quantity: g.total_quantity,
      pending_qty: 0,
      order_quantity: g.total_quantity,
      item_lines: [],
      package_lines: g.packages.map((p: any) => ({
        package_id: p.id,
        package_no: p.package_no,
        reserved_qty: p.total_quantity,
        status: p.status,
      })),
    }));
  }, [readyToShipRows, readyPackagesByOrder]);

  const readyToShipCount = hasReadyToShipOrders
    ? readyToShipTotal || readyToShipRows.length
    : readyPackagePages?.[0]?.group_total ?? 0;

  async function refreshInbox() {
    await Promise.all([
      mutate(), mutateReadyToShipPages(), mutateDepartmentOrderPages(), mutateCuttingOrderPages(),
      mutateAwaitingPackagingPages(), mutatePendingPackagePages(), mutateReadyPackagePages(),
    ]);
  }

  async function createShipmentForOrder(salesOrderId: number | null | undefined) {
    const soId = Number(salesOrderId || 0);
    if (!soId) return;
    const key = `so-${soId}`;
    setShipmentError("");
    setCreatingShipmentFor(key);
    try {
      const created = await api.post("/api/shipments", { sales_order_id: soId });
      await api.post(`/api/shipments/${created.id}/add-ready-packages`);
      await refreshInbox();
      openShipment(soId, created.id);
    } catch (e: any) {
      setShipmentError(e?.message || localizeError("Failed to create shipment"));
    } finally {
      setCreatingShipmentFor(null);
    }
  }

  function openShipment(salesOrderId: number | null | undefined, shipmentId?: number | null) {
    const soId = Number(salesOrderId || 0);
    const shId = Number(shipmentId || 0);
    const qs = new URLSearchParams();
    if (soId > 0) qs.set("so_id", String(soId));
    if (shId > 0) qs.set("shipment_id", String(shId));
    router.push(`/shipments${qs.toString() ? `?${qs.toString()}` : ""}`);
  }

  function textileLine(row: any) {
    const textileName = String(row?.textile_name || "").trim();
    if (!textileName) return null;
    return <div className="text-[11px] text-slate-500">{t("field.textile")}: {textileName}</div>;
  }

  return (
    <div>
      <PageHeader
        title={t("page.deptInbox.title", { dept: deptLabel })}
        subtitle={t("page.deptInbox.subtitle")}
        actions={code === "FGS" ? <StocktakeLink /> : undefined}
      />
      {!isCuttingDepartment && <div className="mb-4">
        <input type="search" className="input max-w-xl" aria-label={`${t("common.search")} ${deptLabel}`}
          placeholder={t("common.search")} maxLength={100} value={departmentSearch}
          onChange={(event) => setDepartmentSearch(event.target.value)} />
      </div>}
      {(isLoading || departmentOrdersLoading || cuttingOrdersLoading) && <div className="card p-4 text-sm text-slate-500">{t("common.loading")}</div>}
      {isCuttingDepartment ? (
        <div className="min-w-0 space-y-2">
          {cuttingOrdersError ? <div role="alert" className="text-sm text-red-700">{String(cuttingOrdersError.message || cuttingOrdersError)}</div> : null}
          <CuttingOrderList
            key={code}
            rows={cuttingWorkOrders}
            cuttingDepartment={code}
            onSearch={setCuttingSearch}
            total={cuttingOrdersTotal}
            t={t}
          />
          {cuttingOrdersHasMore ? (
            <button type="button" className="btn mt-3 h-9 px-3 text-xs" disabled={cuttingOrdersValidating} onClick={() => void setCuttingOrderPageCount((size) => size + 1)}>
              {cuttingOrdersValidating ? t("common.loading") : t("common.loadMore")}
            </button>
          ) : null}
        </div>
      ) : !isLoading && !departmentOrdersLoading ? (
        <div className="min-w-0 space-y-2">
          {departmentOrdersError ? <div role="alert" className="text-sm text-red-700">{String(departmentOrdersError.message || departmentOrdersError)}</div> : null}
          <DepartmentOrderList
            rows={departmentOrders}
            title={t("page.deptInbox.orders", { count: departmentOrdersTotal })}
            emptyLabel={t("page.deptInbox.noOrders")}
            t={t}
          />
          {departmentOrdersHasMore ? (
            <button
              type="button"
              className="btn mt-3 h-9 px-3 text-xs"
              disabled={departmentOrdersValidating}
              onClick={() => void setDepartmentOrderPageCount((size) => size + 1)}
            >
              {departmentOrdersValidating ? t("common.loading") : t("common.loadMore")}
            </button>
          ) : null}
        </div>
      ) : null}

      {isPackagingDepartment && awaitingPackagingLoading ? <div className="card mt-4 p-4 text-sm text-slate-500">{t("common.loading")}</div> : null}
      {isPackagingDepartment && awaitingPackagingError ? <div role="alert" className="text-sm text-red-700">{localizeError(String(awaitingPackagingError.message || awaitingPackagingError))}</div> : null}
      {isPackagingDepartment && awaitingPackagingRows.length > 0 && (
        <div className="card mt-4 overflow-x-auto p-4">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{t("page.deptInbox.awaitingPackaging")} <span className="text-xs font-normal">{awaitingPackagingRows.length} / {awaitingPackagingTotal}</span></h3>
          <table className="table">
            <thead>
              <tr><th>{t("page.workOrder.modelPicture")}</th><th>{t("cuttingInbox.variantPicture")}</th><th>{t("field.production")}</th><th>{t("field.batch")}</th><th>{t("field.modelNo")}</th><th>{t("field.variantNo")}</th><th>{t("field.readyQty")}</th><th>{t("field.sewn")}</th><th>{t("field.packed")}</th></tr>
            </thead>
            <tbody>
              {awaitingPackagingRows.map((r: any) => (
                <tr key={`${r.production_order_id}:${r.production_batch_id ?? "unbatched"}`}>
                  <td><ImageThumbnail imageUrl={r.model_image_url} label={r.model_no || r.model_name || ""} title={t("page.workOrder.modelPicture")} emptyLabel={t("page.workOrder.noImage")} /></td>
                  <td><ImageThumbnail imageUrl={r.material_image_url} label={formatVariantNumber(r.variant_no) || ""} title={t("cuttingInbox.variantPicture")} emptyLabel={t("page.workOrder.noImage")} /></td>
                  <td><Link href={`/production-orders/${r.production_order_id}`} className="mono hover:underline">{r.production_no || "-"}</Link></td>
                  <td>{r.batch_no ? [r.batch_no, r.batch_name].filter(Boolean).join(" · ") : "-"}</td>
                  <td>{r.model_no || r.model_code || "-"}</td>
                  <td>{formatVariantNumber(r.variant_no) || "-"}</td>
                  <td>{r.ready_qty}</td>
                  <td>{r.sewn_passed}</td>
                  <td>{r.already_packed}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {awaitingPackagingHasMore ? (
            <button
              type="button"
              className="btn mt-3"
              disabled={awaitingPackagingValidating}
              onClick={() => void setAwaitingPackagingPageCount((awaitingPackagingPages?.length ?? 1) + 1)}
            >
              {awaitingPackagingValidating ? t("common.loading") : t("common.loadMore")}
            </button>
          ) : null}
        </div>
      )}

      {code === "FGS" && (
        <div className="grid grid-cols-1 gap-4 mt-4 lg:grid-cols-2">
          <section className="card overflow-x-auto p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("page.deptInbox.pendingPackageIntake", { count: pendingPackagesTotal })}
            </h3>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <input
                className="input h-8 min-w-48 flex-1"
                aria-label={`${t("common.search")} ${t("field.package")}`}
                placeholder={`${t("common.search")} ${t("field.package").toLowerCase()}`}
                value={pendingPackageSearch}
                onChange={(event) => setPendingPackageSearch(event.target.value)}
              />
              <span className="text-xs text-slate-500">{pendingPackages.length} / {pendingPackagesTotal}</span>
            </div>
            <table className="table">
              <thead><tr><th>{t("field.salesOrderShort")}</th><th>{t("field.packages")}</th><th>{t("field.qty")}</th><th className="text-right">{t("field.actions")}</th></tr></thead>
              <tbody>
                {pendingPackagesByOrder.map((g) => (
                  <Fragment key={g.key}>
                    <tr key={g.key}>
                      <td>{orderReference(g, "-")}</td>
                      <td>{g.packages.length}</td>
                      <td>{g.total_quantity}</td>
                      <td className="text-right">
                        <ReturnPackages packages={g.packages} onReturned={() => { void refreshInbox(); }} />
                        <button
                          className="btn h-7 px-2 text-[11px]"
                          onClick={() => setExpandedPackageGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
                        >
                          {expandedPackageGroups[g.key] ? t("common.close") : t("btn.open")}
                        </button>
                      </td>
                    </tr>
                    {expandedPackageGroups[g.key] && (
                      <tr key={`${g.key}-details`}>
                        <td colSpan={4} className="bg-slate-50">
                          <table className="table text-xs">
                            <thead>
                              <tr>
                                <th>{t("field.package")}</th>
                                <th>{t("field.qty")}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {g.packages.map((p: any) => (
                                <tr key={p.id}>
                                  <td>{p.package_no}</td>
                                  <td>{p.total_quantity}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
                {pendingPackagesByOrder.length === 0 && (
                  <tr><td colSpan={4} className="text-sm text-slate-400">{t("page.deptInbox.noPendingPackages")}</td></tr>
                )}
              </tbody>
            </table>
            {pendingPackagePages?.[pendingPackagePages.length - 1]?.has_more && (
              <button
                className="btn mt-3"
                type="button"
                disabled={pendingPackagesValidating}
                onClick={() => setPendingPackagePageCount((size) => size + 1)}
              >
                {pendingPackagesValidating ? t("common.loading") : t("common.loadMore")}
              </button>
            )}
          </section>
          <section className="card overflow-x-auto p-4">
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              {t("page.deptInbox.readyToShip", { count: readyToShipCount })}
            </h3>
            {!hasReadyToShipOrders && <div className="mb-3 flex flex-wrap items-center gap-2">
              <input
                className="input h-8 min-w-48 flex-1"
                aria-label={`${t("common.search")} ${t("field.package")}`}
                placeholder={`${t("common.search")} ${t("field.package").toLowerCase()}`}
                value={readyPackageSearch}
                onChange={(event) => setReadyPackageSearch(event.target.value)}
              />
              <span className="text-xs text-slate-500">{readyPackages.length} / {readyPackagesTotal}</span>
            </div>}
            {shipmentError && <div className="mb-2 text-xs text-red-600">{shipmentError}</div>}
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.salesOrderShort")}</th>
                  <th>{t("field.customer")}</th>
                  <th>{t("field.address")}</th>
                  <th>{t("field.items")}</th>
                  <th>{t("field.type")}</th>
                  <th>{t("field.shipmentNo")}</th>
                  <th>{t("field.packages")}</th>
                  <th>{t("field.qty")}</th>
                  <th className="text-right">{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {readyToShipOrders.map((g: any) => {
                  const key = `ready-${String(g.sales_order_id ?? "no-so")}`;
                  const soLabel = orderReference(g, "-");
                  const pendingQty = Number(g.pending_qty || 0);
                  const shipmentType = String(g.shipment_type || g.order_type || "standard").replace(/_/g, " ");
                  const shipmentLabel = g.shipment_no ? `${g.shipment_no} (${statusLabel(String(g.shipment_status || ""), t)})` : t("page.deptInbox.notCreated");
                  const soId = Number(g.sales_order_id || 0);
                  const rowKey = `so-${soId}`;
                  return (
                  <Fragment key={key}>
                    <tr id={soId > 0 ? `shipping-order-${soId}` : undefined}>
                      <td>{soLabel}</td>
                      <td>{g.customer_name || "-"}</td>
                      <td className="max-w-[260px] truncate" title={String(g.destination || g.customer_address || "-")}>
                        {g.destination || g.customer_address || "-"}
                      </td>
                      <td><ShipmentItemLines items={g.item_lines} /></td>
                      <td>{shipmentType}</td>
                      <td>{shipmentLabel}</td>
                      <td>{Number(g.packages || 0)}</td>
                      <td>
                        <div>{Number(g.quantity || 0)}</div>
                        {pendingQty > 0 && <div className="text-[11px] text-amber-700">{t("page.deptInbox.pendingQty", { qty: pendingQty })}</div>}
                      </td>
                      <td className="text-right">
                        <div className="flex justify-end gap-2">
                          {soId > 0 && (
                            <button
                              className="btn h-7 px-2 text-[11px]"
                              onClick={() => openShipment(soId, Number(g.shipment_id || 0))}
                            >
                              {t("btn.open")}
                            </button>
                          )}
                          <button
                            className="btn h-7 px-2 text-[11px]"
                            onClick={() => {
                              if (g.shipment_id) return;
                              createShipmentForOrder(soId);
                            }}
                            disabled={!soId || !!g.shipment_id || creatingShipmentFor === rowKey}
                          >
                            {creatingShipmentFor === rowKey ? t("common.loading") : t("btn.createShipment")}
                          </button>
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                )})}
                {readyToShipOrders.length === 0 && (
                  <tr><td colSpan={9} className="text-sm text-slate-400">{t("page.deptInbox.noReadyToShip")}</td></tr>
                )}
              </tbody>
            </table>
            {hasReadyToShipOrders && readyToShipHasMore && (
              <button
                className="btn mt-3"
                type="button"
                disabled={readyToShipValidating}
                onClick={() => setReadyToShipSize(readyToShipSize + 1)}
              >
                {readyToShipValidating ? t("common.loading") : t("common.loadMore")}
              </button>
            )}
            {!hasReadyToShipOrders && readyPackagePages?.[readyPackagePages.length - 1]?.has_more && (
              <button
                className="btn mt-3"
                type="button"
                disabled={readyPackagesValidating}
                onClick={() => setReadyPackagePageCount((size) => size + 1)}
              >
                {readyPackagesValidating ? t("common.loading") : t("common.loadMore")}
              </button>
            )}
            {hasReadyToShipOrders && (
              <div className="mt-4 border-t border-slate-200 pt-4">
                <h4 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                  {t("field.packages")} ({readyPackagesTotal})
                </h4>
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <input
                    className="input h-8 min-w-48 flex-1"
                    aria-label={`${t("common.search")} ${t("field.package")}`}
                    placeholder={`${t("common.search")} ${t("field.package").toLowerCase()}`}
                    value={readyPackageSearch}
                    onChange={(event) => setReadyPackageSearch(event.target.value)}
                  />
                  <span className="text-xs text-slate-500">{readyPackages.length} / {readyPackagesTotal}</span>
                </div>
                <table className="table text-xs">
                  <thead><tr><th>{t("field.salesOrderShort")}</th><th>{t("field.packages")}</th><th>{t("field.qty")}</th></tr></thead>
                  <tbody>
                    {readyPackagesByOrder.map((group) => (
                      <tr key={`ready-package-${group.key}`}>
                        <td>{orderReference(group, "-")}</td>
                        <td>{group.packages.length}</td>
                        <td>{group.total_quantity}</td>
                      </tr>
                    ))}
                    {readyPackagesByOrder.length === 0 && (
                      <tr><td colSpan={3} className="text-sm text-slate-400">{t("page.deptInbox.noReadyToShip")}</td></tr>
                    )}
                  </tbody>
                </table>
                {readyPackagePages?.[readyPackagePages.length - 1]?.has_more && (
                  <button
                    className="btn mt-3"
                    type="button"
                    disabled={readyPackagesValidating}
                    onClick={() => setReadyPackagePageCount((size) => size + 1)}
                  >
                    {readyPackagesValidating ? t("common.loading") : t("common.loadMore")}
                  </button>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
