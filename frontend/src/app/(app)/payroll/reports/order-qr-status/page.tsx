"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { CheckCircle2, Clock3, FileSearch, QrCode, Search } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import type {
  OrderQrStatusCell,
  OrderQrStatusLabel,
  OrderQrStatusOrderOption,
  OrderQrStatusResponse,
} from "@/lib/orderQrStatus";

const DEFAULT_PAGE_SIZE = 100;

function number(value: number | string | null | undefined, lang: string) {
  return Number(value || 0).toLocaleString(lang, { maximumFractionDigits: 2 });
}

function compactList(values: string[]) {
  return values.length ? values.join(", ") : "—";
}

function MatrixValue({ quantity, labels, tone, lang }: {
  quantity: number | string;
  labels: number;
  tone: "neutral" | "success" | "pending";
  lang: string;
}) {
  const tones = {
    neutral: "bg-[#f7f5ef] text-[#3f3a2f]",
    success: labels ? "bg-emerald-50 text-emerald-800" : "bg-white text-[#a09a8b]",
    pending: labels ? "bg-amber-50 text-amber-900" : "bg-white text-[#a09a8b]",
  };
  return (
    <td className={`border-l border-[#e4dfd2] px-2 py-2 text-center tabular-nums ${tones[tone]}`}>
      <div className="font-medium">{number(quantity, lang)}</div>
      <div className="mt-0.5 text-[10px] opacity-70">{labels} QR</div>
    </td>
  );
}

function LabelStatus({ label, t }: { label: OrderQrStatusLabel; t: (key: string) => string }) {
  if (label.status === "scanned") {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-emerald-700">
        <CheckCircle2 className="h-4 w-4" />
        {t("page.orderQr.scanned")}
      </span>
    );
  }
  return (
    <div>
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-amber-700">
        <Clock3 className="h-4 w-4" />
        {t("page.orderQr.notScanned")}
      </span>
      {label.return_count > 0 && (
        <div className="mt-1 text-xs text-[#817966]">
          {t("page.orderQr.returned").replace("{count}", String(label.return_count))}
        </div>
      )}
    </div>
  );
}

export default function OrderQrStatusPage() {
  const { t, lang } = useT();
  const [draftOrder, setDraftOrder] = useState("");
  const [selectedOrder, setSelectedOrder] = useState("");
  const [status, setStatus] = useState<"" | "scanned" | "available">("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const optionUrl = `/api/payroll/reports/order-qr-status/orders?search=${encodeURIComponent(draftOrder.trim())}&limit=50`;
  const { data: orderOptions = [], error: optionsError } = useSWR<OrderQrStatusOrderOption[]>(optionUrl, fetcher);
  const reportUrl = useMemo(() => {
    if (!selectedOrder) return null;
    const params = new URLSearchParams({
      order_no: selectedOrder,
      limit: String(pageSize),
      offset: String((page - 1) * pageSize),
    });
    if (status) params.set("status", status);
    return `/api/payroll/reports/order-qr-status?${params.toString()}`;
  }, [page, pageSize, selectedOrder, status]);
  const { data, error, isLoading } = useSWR<OrderQrStatusResponse>(reportUrl, fetcher);

  function chooseOrder(event: React.FormEvent) {
    event.preventDefault();
    const exact = draftOrder.trim();
    if (!exact) return;
    setSelectedOrder(exact);
    setPage(1);
  }

  function cellFor(cells: OrderQrStatusCell[], size: string) {
    return cells.find((cell) => cell.size === size) || {
      size,
      issued_labels: 0,
      scanned_labels: 0,
      available_labels: 0,
      issued_quantity: 0,
      scanned_quantity: 0,
      available_quantity: 0,
    };
  }

  return (
    <div className="space-y-4">
      <PageHeader title={t("page.orderQr.title")} subtitle={t("page.orderQr.subtitle")} />

      <form className="card p-4" onSubmit={chooseOrder}>
        <div className="grid items-end gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <label className="min-w-0">
            <span className="label">{t("page.orderQr.findOrder")}</span>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
              <input
                className="input pl-9"
                list="order-qr-options"
                value={draftOrder}
                onChange={(event) => setDraftOrder(event.target.value)}
                placeholder={t("page.orderQr.orderPlaceholder")}
                autoComplete="off"
              />
              <datalist id="order-qr-options">
                {orderOptions.map((option) => (
                  <option key={option.order_no} value={option.order_no}>
                    {[...option.production_nos, ...option.model_codes].join(" · ")}
                  </option>
                ))}
              </datalist>
            </div>
            <p className="mt-1.5 text-xs text-[#817966]">{t("page.orderQr.findOrderHint")}</p>
          </label>
          <button type="submit" className="btn btn-primary" disabled={!draftOrder.trim()}>
            <FileSearch />
            <span>{t("page.orderQr.viewOrder")}</span>
          </button>
        </div>
        {optionsError && <p className="mt-3 text-sm text-red-700">{t("page.orderQr.orderLookupFailed")}</p>}
      </form>

      {!selectedOrder ? (
        <section className="card px-5 py-12 text-center">
          <QrCode className="mx-auto h-8 w-8 text-[#9b9482]" />
          <h2 className="mt-3 text-base font-semibold text-[#373226]">{t("page.orderQr.chooseOrderTitle")}</h2>
          <p className="mx-auto mt-1 max-w-lg text-sm text-[#817966]">{t("page.orderQr.chooseOrderHint")}</p>
        </section>
      ) : error ? (
        <div className="card border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error?.message || t("page.orderQr.loadFailed")}
        </div>
      ) : isLoading || !data ? (
        <div className="card p-10 text-center text-sm text-[#817966]">{t("common.loading")}</div>
      ) : (
        <>
          <section className="card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#e4dfd2] pb-4">
              <div>
                <div className="label">{t("page.orderQr.selectedOrder")}</div>
                <h2 className="mt-1 text-xl font-semibold text-[#302b21]">{data.order_no}</h2>
              </div>
              <div className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                <div><span className="text-[#817966]">{t("page.orderQr.productionOrder")}:</span> {compactList(data.production_nos)}</div>
                <div><span className="text-[#817966]">{t("page.orderQr.model")}:</span> {compactList(data.model_codes)}</div>
                <div><span className="text-[#817966]">{t("page.orderQr.batch")}:</span> {compactList(data.batch_nos)}</div>
              </div>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="kpi-card">
                <div className="label">{t("page.orderQr.issued")}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums">{number(data.total_quantity, lang)}</div>
                <div className="mt-1 text-xs text-[#817966]">{number(data.total_labels, lang)} QR</div>
              </div>
              <div className="kpi-card border-emerald-200 bg-emerald-50/60">
                <div className="label text-emerald-700">{t("page.orderQr.scanned")}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-emerald-800">{number(data.scanned_quantity, lang)}</div>
                <div className="mt-1 text-xs text-emerald-700">{number(data.scanned_labels, lang)} QR</div>
              </div>
              <div className="kpi-card border-amber-200 bg-amber-50/60">
                <div className="label text-amber-700">{t("page.orderQr.notScanned")}</div>
                <div className="mt-1 text-2xl font-semibold tabular-nums text-amber-900">{number(data.available_quantity, lang)}</div>
                <div className="mt-1 text-xs text-amber-700">{number(data.available_labels, lang)} QR</div>
              </div>
            </div>
          </section>

          <section className="card overflow-hidden">
            <div className="border-b border-[#e4dfd2] px-4 py-3">
              <h2 className="app-card-title">{t("page.orderQr.matrixTitle")}</h2>
              <p className="mt-1 text-xs text-[#817966]">{t("page.orderQr.matrixHint")}</p>
            </div>
            <div className="max-w-full overflow-x-auto">
              <table className="min-w-max border-collapse text-xs">
                <thead>
                  <tr className="bg-[#f0eee7] text-[#4c4638]">
                    <th rowSpan={2} className="sticky left-0 z-20 min-w-56 border-b border-r border-[#d8d2c2] bg-[#f0eee7] px-3 py-2 text-left">
                      {t("page.orderQr.operation")}
                    </th>
                    {data.sizes.map((size) => (
                      <th key={size} colSpan={3} className="border-b border-r border-[#d8d2c2] px-3 py-2 text-center text-sm font-semibold">{size}</th>
                    ))}
                    <th colSpan={3} className="border-b border-[#d8d2c2] px-3 py-2 text-center text-sm font-semibold">{t("page.orderQr.total")}</th>
                  </tr>
                  <tr className="bg-[#f7f5ef] text-[10px] uppercase tracking-wide text-[#706957]">
                    {[...data.sizes, "total"].flatMap((size) => [
                      <th key={`${size}-issued`} className="min-w-[76px] border-b border-l border-[#e4dfd2] px-2 py-1.5">{t("page.orderQr.issued")}</th>,
                      <th key={`${size}-scanned`} className="min-w-[76px] border-b border-l border-[#e4dfd2] px-2 py-1.5 text-emerald-700">{t("page.orderQr.scanned")}</th>,
                      <th key={`${size}-available`} className="min-w-[76px] border-b border-l border-[#e4dfd2] px-2 py-1.5 text-amber-700">{t("page.orderQr.notScanned")}</th>,
                    ])}
                  </tr>
                </thead>
                <tbody>
                  {data.operations.map((operation) => (
                    <tr key={`${operation.operation_section}-${operation.operation_code}-${operation.operation_name}`} className="border-b border-[#ece8dd]">
                      <th className="sticky left-0 z-10 border-r border-[#d8d2c2] bg-white px-3 py-2 text-left font-medium text-[#373226]">
                        <div>{operation.operation_name}</div>
                        {operation.operation_code && <div className="mt-0.5 font-mono text-[10px] font-normal text-[#8a8472]">{operation.operation_code}</div>}
                      </th>
                      {data.sizes.map((size) => {
                        const cell = cellFor(operation.cells, size);
                        return [
                          <MatrixValue key={`${size}-issued`} quantity={cell.issued_quantity} labels={cell.issued_labels} tone="neutral" lang={lang} />,
                          <MatrixValue key={`${size}-scanned`} quantity={cell.scanned_quantity} labels={cell.scanned_labels} tone="success" lang={lang} />,
                          <MatrixValue key={`${size}-available`} quantity={cell.available_quantity} labels={cell.available_labels} tone="pending" lang={lang} />,
                        ];
                      })}
                      <MatrixValue quantity={operation.issued_quantity} labels={operation.issued_labels} tone="neutral" lang={lang} />
                      <MatrixValue quantity={operation.scanned_quantity} labels={operation.scanned_labels} tone="success" lang={lang} />
                      <MatrixValue quantity={operation.available_quantity} labels={operation.available_labels} tone="pending" lang={lang} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card overflow-hidden">
            <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#e4dfd2] px-4 py-3">
              <div>
                <h2 className="app-card-title">{t("page.orderQr.detailsTitle")}</h2>
                <p className="mt-1 text-xs text-[#817966]">{t("page.orderQr.detailsHint")}</p>
              </div>
              <label className="w-full sm:w-52">
                <span className="label">{t("page.orderQr.status")}</span>
                <select
                  className="input"
                  value={status}
                  onChange={(event) => {
                    setStatus(event.target.value as "" | "scanned" | "available");
                    setPage(1);
                  }}
                >
                  <option value="">{t("common.all")}</option>
                  <option value="scanned">{t("page.orderQr.scanned")}</option>
                  <option value="available">{t("page.orderQr.notScanned")}</option>
                </select>
              </label>
            </div>
            <div className="max-w-full overflow-x-auto">
              <table className="min-w-[980px] w-full text-sm">
                <thead className="bg-[#f7f5ef] text-left text-xs uppercase tracking-wide text-[#706957]">
                  <tr>
                    <th className="px-4 py-2.5">{t("page.orderQr.qrCode")}</th>
                    <th className="px-4 py-2.5">{t("page.orderQr.status")}</th>
                    <th className="px-4 py-2.5">{t("page.orderQr.operation")}</th>
                    <th className="px-4 py-2.5">{t("page.orderQr.sizeQuantity")}</th>
                    <th className="px-4 py-2.5">{t("page.orderQr.employee")}</th>
                    <th className="px-4 py-2.5">{t("page.orderQr.scanTime")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((label) => (
                    <tr key={label.id} className="border-t border-[#ece8dd] align-top">
                      <td className="px-4 py-3">
                        <div className="font-mono font-medium text-[#302b21]">{label.qr_token}</div>
                        <div className="mt-1 max-w-56 truncate font-mono text-[10px] text-[#8a8472]" title={label.label_uid}>{label.label_uid}</div>
                      </td>
                      <td className="px-4 py-3"><LabelStatus label={label} t={t} /></td>
                      <td className="px-4 py-3">
                        <div>{label.operation_name || label.operation_code || "—"}</div>
                        {label.operation_code && label.operation_name && <div className="mt-1 font-mono text-xs text-[#817966]">{label.operation_code}</div>}
                      </td>
                      <td className="px-4 py-3 tabular-nums">
                        <div>{label.size || "—"}</div>
                        <div className="mt-1 text-xs text-[#817966]">{number(label.quantity, lang)} {t("page.orderQr.pieces")}</div>
                      </td>
                      <td className="px-4 py-3">{label.employee_name || "—"}</td>
                      <td className="px-4 py-3 tabular-nums">
                        {label.last_scanned_at ? new Date(label.last_scanned_at).toLocaleString(lang) : "—"}
                      </td>
                    </tr>
                  ))}
                  {!data.items.length && (
                    <tr><td colSpan={6} className="px-4 py-10 text-center text-[#817966]">{t("page.orderQr.noLabels")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <PaginationControls
              page={page}
              pageSize={pageSize}
              total={data.total}
              count={data.items.length}
              pageSizeOptions={[50, 100, 200, 500]}
              onPageChange={setPage}
              onPageSizeChange={(next) => {
                setPageSize(next);
                setPage(1);
              }}
            />
          </section>
        </>
      )}
    </div>
  );
}
