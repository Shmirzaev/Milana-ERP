"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, ExternalLink, PackageSearch, Printer, Search } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import { api } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type TraceabilityResult = {
  subject_type: string;
  subject_id?: number | null;
  generated_at: string;
  production_order?: any | null;
  sales_order?: any | null;
  customer?: any | null;
  brand?: any | null;
  collection?: any | null;
  model?: any | null;
  package?: any | null;
  packages?: any[];
  package_items?: any[];
  package_scan_history?: any[];
  bundles?: any[];
  material_batches?: any[];
  cutting_records?: any[];
  printing_records?: any[];
  sewing_records?: any[];
  quality_checks?: any[];
  packaging_records?: any[];
  waste_summary?: any[];
  shipment?: any | null;
  shipment_packages?: any[];
  shipment_package_scan_logs?: any[];
  warehouse_location?: any | null;
  gaps?: string[];
};

type SearchMode = "auto" | "package" | "bundle" | "production" | "shipment";
type TimelineStage = "cutting" | "printing" | "sewing" | "packaging" | "bundle_scan" | "package_scan" | "shipment_scan";

function valueOrDash(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function fmtDate(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "-";
}

function buildTimeline(data: TraceabilityResult | null) {
  if (!data) return [];
  const rows: Array<{ key: string; stage: TimelineStage; when?: string | null; detail: string; ref?: string | null }> = [];
  for (const row of data.cutting_records || []) {
    rows.push({
      key: `cut-${row.id}`,
      stage: "cutting",
      when: row.created_at,
      detail: `${row.passed_pieces || 0} / ${row.cut_pieces || 0}`,
      ref: row.fabric_batch_id ? `Batch #${row.fabric_batch_id}` : null,
    });
  }
  for (const bundle of data.bundles || []) {
    for (const scan of bundle.scan_logs || []) {
      rows.push({
        key: `bundle-${bundle.id}-${scan.id}`,
        stage: "bundle_scan",
        when: scan.scanned_at,
        detail: `${bundle.bundle_no} - ${scan.scan_type}`,
        ref: bundle.status,
      });
    }
  }
  for (const row of data.printing_records || []) {
    rows.push({ key: `print-${row.id}`, stage: "printing", when: row.created_at, detail: `${row.passed_qty || 0} passed`, ref: row.print_type });
  }
  for (const row of data.sewing_records || []) {
    rows.push({ key: `sew-${row.id}`, stage: "sewing", when: row.created_at, detail: `${row.passed_qty || 0} passed`, ref: row.line_name });
  }
  for (const row of data.packaging_records || []) {
    rows.push({ key: `pack-${row.id}`, stage: "packaging", when: row.created_at, detail: `${row.packed_qty || 0} packed`, ref: row.packaging_material_used });
  }
  for (const scan of data.package_scan_history || []) {
    rows.push({ key: `pkg-${scan.id}`, stage: "package_scan", when: scan.scanned_at, detail: scan.scan_type, ref: scan.location });
  }
  for (const scan of data.shipment_package_scan_logs || []) {
    rows.push({ key: `shipscan-${scan.id}`, stage: "shipment_scan", when: scan.scanned_at, detail: scan.scan_result, ref: scan.message });
  }
  return rows.sort((a, b) => String(a.when || "").localeCompare(String(b.when || "")));
}

function stageLabel(stage: TimelineStage, t: (key: string) => string) {
  if (stage === "cutting" || stage === "printing" || stage === "sewing" || stage === "packaging") return operationLabel(stage, t);
  if (stage === "bundle_scan") return t("page.traceability.bundleScan");
  if (stage === "package_scan") return t("page.traceability.packageScan");
  return t("page.traceability.shipmentScan");
}

function lookupPaths(needle: string, mode: SearchMode) {
  const encoded = encodeURIComponent(needle);
  if (mode === "package") return [`/api/traceability/package/barcode/${encoded}`, `/api/traceability/package/${encoded}`];
  if (mode === "bundle") return [`/api/traceability/bundle/${encoded}`];
  if (mode === "production") return [`/api/traceability/production-order/${encoded}`];
  if (mode === "shipment") return [`/api/traceability/shipment/${encoded}`];
  return [
    `/api/traceability/package/barcode/${encoded}`,
    `/api/traceability/package/${encoded}`,
    `/api/traceability/bundle/${encoded}`,
    `/api/traceability/production-order/${encoded}`,
    `/api/traceability/shipment/${encoded}`,
  ];
}

export default function TraceabilityPage() {
  const { t } = useT();
  const searchParams = useSearchParams();
  const { me } = useMe();
  const canExport = can(me, "traceability.export");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("auto");
  const [data, setData] = useState<TraceabilityResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const timeline = useMemo(() => buildTimeline(data), [data]);

  const tryLookup = useCallback(async (path: string) => {
    return api.get<TraceabilityResult>(path);
  }, []);

  const lookupValue = useCallback(async (needle: string, selectedMode: SearchMode) => {
    const cleaned = needle.trim();
    if (!cleaned) return;
    setBusy(true);
    setError("");
    setData(null);
    try {
      let lastError = "";
      for (const path of lookupPaths(cleaned, selectedMode)) {
        try {
          const result = await tryLookup(path);
          setData(result);
          return;
        } catch (err: any) {
          lastError = err?.message || "";
        }
      }
      setError(lastError || t("page.traceability.notFound"));
    } finally {
      setBusy(false);
    }
  }, [t, tryLookup]);

  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());
    const candidates: Array<[SearchMode, string | null]> = [
      ["package", params.get("package") || params.get("barcode")],
      ["bundle", params.get("bundle")],
      ["production", params.get("production_order") || params.get("production")],
      ["shipment", params.get("shipment")],
      ["auto", params.get("q")],
    ];
    const match = candidates.find(([, value]) => String(value || "").trim());
    if (!match) return;
    const [nextMode, nextQuery] = match;
    const cleaned = String(nextQuery || "").trim();
    setMode(nextMode);
    setQuery(cleaned);
    void lookupValue(cleaned, nextMode);
  }, [lookupValue, searchParams]);

  async function lookup(event?: FormEvent) {
    event?.preventDefault();
    const needle = query.trim();
    if (!needle) return;
    await lookupValue(needle, mode);
  }

  function openExport() {
    if (!data) return;
    if (data.subject_type === "shipment" && data.shipment?.id) {
      api.openLabel(`/api/traceability/export/shipment/${data.shipment.id}`);
      return;
    }
    const packageId = data.package?.id || data.packages?.[0]?.id;
    if (packageId) api.openLabel(`/api/traceability/export/package/${packageId}`);
  }

  const packageId = data?.package?.id || data?.packages?.[0]?.id;
  const productionOrderId = data?.production_order?.id;
  const shipmentId = data?.shipment?.id;

  return (
    <div>
      <PageHeader
        title={t("page.traceability.title")}
        subtitle={t("page.traceability.subtitle")}
        actions={data && canExport ? (
          <button type="button" className="btn" onClick={openExport}>
            <Printer />{t("page.traceability.printPassport")}
          </button>
        ) : null}
      />

      <form onSubmit={lookup} className="card mb-5 p-4">
        <div className="grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)_auto] lg:items-end">
          <div>
            <label className="label">{t("field.type")}</label>
            <select className="input" value={mode} onChange={(event) => setMode(event.target.value as SearchMode)}>
              <option value="auto">{t("page.traceability.modeAuto")}</option>
              <option value="package">{t("field.packageNo")}</option>
              <option value="bundle">{t("field.bundleNo")}</option>
              <option value="production">{t("field.productionNo")}</option>
              <option value="shipment">{t("field.shipmentNo")}</option>
            </select>
          </div>
          <div>
            <label className="label">{t("common.search")}</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
              <input
                className="input pl-9"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("page.traceability.searchPlaceholder")}
              />
            </div>
          </div>
          <button className="btn btn-primary" disabled={busy || !query.trim()}>
            <PackageSearch />{busy ? t("common.loading") : t("btn.lookup")}
          </button>
        </div>
      </form>

      {error && <div className="mb-5 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}

      {data && (
        <div className="space-y-5">
          {(data.gaps || []).length > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-900">
                <AlertTriangle className="h-4 w-4" />{t("page.traceability.gaps")}
              </div>
              <ul className="space-y-1 text-sm text-amber-800">
                {(data.gaps || []).map((gap) => <li key={gap}>{gap}</li>)}
              </ul>
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-3">
            <section className="card p-4">
              <h2 className="app-card-title mb-3">{t("page.traceability.productIdentity")}</h2>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.packageNo")}</dt><dd>{valueOrDash(data.package?.package_no || data.packages?.[0]?.package_no)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.barcode")}</dt><dd className="font-mono text-xs">{valueOrDash(data.package?.barcode || data.packages?.[0]?.barcode)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.model")}</dt><dd>{valueOrDash(data.model?.code || data.model?.name)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.brand")}</dt><dd>{valueOrDash(data.brand?.name)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.collection")}</dt><dd>{valueOrDash(data.collection?.name)}</dd></div>
              </dl>
            </section>

            <section className="card p-4">
              <h2 className="app-card-title mb-3">{t("page.traceability.orderLinks")}</h2>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.productionNo")}</dt><dd>{valueOrDash(data.production_order?.production_no || data.production_order?.order_no)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.orderNo")}</dt><dd>{valueOrDash(data.sales_order?.order_no)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.customer")}</dt><dd>{valueOrDash(data.customer?.name)}</dd></div>
                <div className="flex flex-wrap gap-2 pt-2">
                  {packageId && <Link className="btn h-7 px-2 text-[11px]" href={`/packages/${packageId}`}>{t("field.packageNo")}<ExternalLink /></Link>}
                  {productionOrderId && <Link className="btn h-7 px-2 text-[11px]" href={`/production-orders/${productionOrderId}`}>{t("field.productionNo")}<ExternalLink /></Link>}
                  {shipmentId && <Link className="btn h-7 px-2 text-[11px]" href={`/shipments?shipment_id=${shipmentId}`}>{t("field.shipmentNo")}<ExternalLink /></Link>}
                </div>
              </dl>
            </section>

            <section className="card p-4">
              <h2 className="app-card-title mb-3">{t("page.traceability.warehouseShipment")}</h2>
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.warehouse")}</dt><dd>{valueOrDash(data.warehouse_location?.warehouse_name)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.cell")}</dt><dd>{valueOrDash(data.warehouse_location?.location)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.shipmentNo")}</dt><dd>{valueOrDash(data.shipment?.shipment_no)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-[#8a8472]">{t("field.status")}</dt><dd>{data.shipment?.status ? statusLabel(data.shipment.status, t) : "-"}</dd></div>
              </dl>
            </section>
          </div>

          <section className="card overflow-x-auto">
            <div className="border-b border-[#ecebe3] p-4">
              <h2 className="app-card-title">{t("page.traceability.timeline")}</h2>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.when")}</th>
                  <th>{t("field.operation")}</th>
                  <th>{t("field.description")}</th>
                  <th>{t("field.reference")}</th>
                </tr>
              </thead>
              <tbody>
                {timeline.map((row) => (
                  <tr key={row.key}>
                    <td>{fmtDate(row.when)}</td>
                    <td>{stageLabel(row.stage, t)}</td>
                    <td>{row.detail}</td>
                    <td>{valueOrDash(row.ref)}</td>
                  </tr>
                ))}
                {timeline.length === 0 && <tr><td colSpan={4} className="text-sm text-slate-400">{t("page.traceability.noTimeline")}</td></tr>}
              </tbody>
            </table>
          </section>

          <div className="grid gap-4 xl:grid-cols-2">
            <section className="card overflow-x-auto">
              <div className="border-b border-[#ecebe3] p-4"><h2 className="app-card-title">{t("page.traceability.materialOrigin")}</h2></div>
              <table className="table">
                <thead><tr><th>{t("field.batchNo")}</th><th>{t("field.item")}</th><th>{t("field.color")}</th><th>{t("field.qty")}</th><th>{t("field.qc")}</th></tr></thead>
                <tbody>
                  {(data.material_batches || []).map((row) => (
                    <tr key={row.id}>
                      <td>{row.batch_no}</td>
                      <td>{row.item_sku} - {row.item_name}</td>
                      <td>{valueOrDash(row.color)}</td>
                      <td>{valueOrDash(row.quantity)} {valueOrDash(row.unit)}</td>
                      <td>{statusLabel(String(row.qc_status || ""), t)}</td>
                    </tr>
                  ))}
                  {(data.material_batches || []).length === 0 && <tr><td colSpan={5} className="text-sm text-slate-400">{t("page.traceability.noMaterials")}</td></tr>}
                </tbody>
              </table>
            </section>

            <section className="card overflow-x-auto">
              <div className="border-b border-[#ecebe3] p-4"><h2 className="app-card-title">{t("page.traceability.packages")}</h2></div>
              <table className="table">
                <thead><tr><th>{t("field.packageNo")}</th><th>{t("field.barcode")}</th><th>{t("field.totalQty")}</th><th>{t("field.status")}</th><th>{t("field.cell")}</th></tr></thead>
                <tbody>
                  {(data.packages || []).map((row) => (
                    <tr key={row.id}>
                      <td>{row.package_no}</td>
                      <td className="font-mono text-xs">{row.barcode}</td>
                      <td>{row.total_quantity}</td>
                      <td>{statusLabel(String(row.status || ""), t)}</td>
                      <td>{valueOrDash(row.storage_location)}</td>
                    </tr>
                  ))}
                  {(data.packages || []).length === 0 && <tr><td colSpan={5} className="text-sm text-slate-400">{t("page.packages.empty")}</td></tr>}
                </tbody>
              </table>
            </section>
          </div>
        </div>
      )}
    </div>
  );
}
