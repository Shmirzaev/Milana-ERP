"use client";

import { useMemo, useRef, useState, type FormEvent } from "react";
import { CheckCircle2, QrCode, RefreshCw, Search } from "lucide-react";
import useSWR from "swr";

import PageHeader from "@/components/PageHeader";
import { api, fetcher } from "@/lib/api";
import { LIVE_DATA_SWR_OPTIONS } from "@/lib/liveData";
import { useT } from "@/lib/i18n";
import { parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

type ReceiveOption = {
  work_order_id: number;
  source_work_order_id: number;
  production_order_id: number;
  production_batch_id?: number | null;
  production_no?: string | null;
  order_no?: string | null;
  model_code?: string | null;
  model_name?: string | null;
  batch_no?: string | null;
  batch_name?: string | null;
  sewing_passed: number;
  received_quantity: number;
  available_quantity: number;
};

type Receipt = {
  id: number;
  production_order_id: number;
  production_batch_id?: number | null;
  production_no?: string | null;
  order_no?: string | null;
  model_code?: string | null;
  model_name?: string | null;
  batch_no?: string | null;
  batch_name?: string | null;
  bundle_no?: string | null;
  size?: string | null;
  color?: string | null;
  quantity: number;
  receive_method: "scan" | "manual";
  created_at: string;
  remaining_available?: number;
};

function latestBundleCode(raw: string) {
  const text = String(raw || "").trimStart();
  const markerIndex = text.toUpperCase().lastIndexOf("BUNDLE:");
  return markerIndex > 0 ? text.slice(markerIndex) : text;
}

function orderLabel(row: { order_no?: string | null; production_no?: string | null; production_order_id: number }) {
  return row.order_no || row.production_no || `#${row.production_order_id}`;
}

function batchLabel(row: { batch_no?: string | null; batch_name?: string | null }) {
  return [row.batch_no, row.batch_name].filter(Boolean).join(" - ") || "-";
}

function modelLabel(row: { model_code?: string | null; model_name?: string | null }) {
  return [row.model_code, row.model_name].filter(Boolean).join(" - ") || "-";
}

export default function PackagingReceivePage() {
  const { t } = useT();
  const scanInputRef = useRef<HTMLInputElement>(null);
  const [scanCode, setScanCode] = useState("");
  const [scanBusy, setScanBusy] = useState(false);
  const [scanMessage, setScanMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [manualBusyKey, setManualBusyKey] = useState("");
  const [manualMessage, setManualMessage] = useState("");
  const [quantities, setQuantities] = useState<Record<string, NumberInputValue>>({});

  const optionsUrl = useMemo(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (search) params.set("q", search);
    return `/api/packaging/receive-options?${params.toString()}`;
  }, [search]);
  const { data: options = [], mutate: mutateOptions, isLoading } = useSWR<ReceiveOption[]>(
    optionsUrl,
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );
  const { data: receipts = [], mutate: mutateReceipts } = useSWR<Receipt[]>(
    "/api/packaging/receipts?limit=50",
    fetcher,
    LIVE_DATA_SWR_OPTIONS,
  );

  function focusScan() {
    window.requestAnimationFrame(() => {
      scanInputRef.current?.focus();
      scanInputRef.current?.select();
    });
  }

  async function refreshData() {
    await Promise.all([mutateOptions(), mutateReceipts()]);
  }

  async function receiveScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = latestBundleCode(scanCode).trim();
    if (!code || scanBusy) return;
    setScanBusy(true);
    setScanMessage(null);
    try {
      const receipt = await api.post<Receipt>("/api/packaging/receive-from-sewing", { bundle_code: code });
      setScanCode("");
      setScanMessage({
        tone: "success",
        text: t("page.packagingReceive.scanSuccess", {
          bundle: receipt.bundle_no || "-",
          quantity: receipt.quantity,
          order: orderLabel(receipt),
        }),
      });
      await refreshData();
    } catch (error: any) {
      setScanMessage({ tone: "error", text: String(error?.message || t("page.packagingReceive.receiveFailed")) });
    } finally {
      setScanBusy(false);
      focusScan();
    }
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchDraft.trim());
  }

  async function receiveManual(option: ReceiveOption) {
    const key = `${option.work_order_id}:${option.production_batch_id ?? ""}`;
    const quantity = Number(quantities[key] ?? option.available_quantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setManualMessage(t("page.packagingReceive.positiveQuantity"));
      return;
    }
    setManualBusyKey(key);
    setManualMessage("");
    try {
      const receipt = await api.post<Receipt>("/api/packaging/receive-from-sewing", {
        work_order_id: option.work_order_id,
        production_batch_id: option.production_batch_id || null,
        quantity,
      });
      setQuantities((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      setManualMessage(t("page.packagingReceive.manualSuccess", {
        quantity: receipt.quantity,
        order: orderLabel(receipt),
      }));
      await refreshData();
    } catch (error: any) {
      setManualMessage(String(error?.message || t("page.packagingReceive.receiveFailed")));
    } finally {
      setManualBusyKey("");
    }
  }

  return (
    <div>
      <PageHeader
        title={t("page.packagingReceive.title")}
        subtitle={t("page.packagingReceive.subtitle")}
        actions={(
          <button type="button" className="btn" onClick={refreshData}>
            <RefreshCw className="h-4 w-4" />
            {t("btn.refresh")}
          </button>
        )}
      />

      <section className="card mb-4 p-4">
        <div className="mb-3">
          <h2 className="text-base font-semibold text-[#14110b]">{t("page.packagingReceive.scanTitle")}</h2>
          <p className="mt-1 text-sm text-[#8a8472]">{t("page.packagingReceive.scanHint")}</p>
        </div>
        <form className="flex flex-col gap-2 md:flex-row" onSubmit={receiveScan}>
          <div className="relative flex-1">
            <QrCode className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
            <input
              ref={scanInputRef}
              className="input pl-9"
              autoFocus
              autoComplete="off"
              value={scanCode}
              onChange={(event) => setScanCode(latestBundleCode(event.target.value))}
              onFocus={(event) => event.currentTarget.select()}
              placeholder={t("page.packagingReceive.scanPlaceholder")}
            />
          </div>
          <button type="submit" className="btn btn-primary shrink-0" disabled={scanBusy || !scanCode.trim()}>
            <CheckCircle2 className="h-4 w-4" />
            {scanBusy ? t("page.packagingReceive.receiving") : t("page.packagingReceive.receive")}
          </button>
        </form>
        {scanMessage && (
          <div className={`mt-3 text-sm ${scanMessage.tone === "error" ? "text-red-700" : "text-green-700"}`} role="status">
            {scanMessage.text}
          </div>
        )}
      </section>

      <section className="card mb-4 p-4">
        <div className="mb-3 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-base font-semibold text-[#14110b]">{t("page.packagingReceive.manualTitle")}</h2>
            <p className="mt-1 text-sm text-[#8a8472]">{t("page.packagingReceive.manualHint")}</p>
          </div>
          <form className="flex w-full gap-2 md:max-w-md" onSubmit={submitSearch}>
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
              <input
                className="input pl-9"
                value={searchDraft}
                onChange={(event) => setSearchDraft(event.target.value)}
                placeholder={t("page.packagingReceive.searchPlaceholder")}
              />
            </div>
            <button type="submit" className="btn">{t("common.search")}</button>
          </form>
        </div>
        {manualMessage && <div className="mb-3 text-sm text-[#56503f]">{manualMessage}</div>}
        <div className="overflow-x-auto">
          <table className="table min-w-[900px]">
            <thead>
              <tr>
                <th>{t("field.orderNo")}</th>
                <th>{t("field.model")}</th>
                <th>{t("field.batch")}</th>
                <th className="text-right">{t("page.packagingReceive.sewingPassed")}</th>
                <th className="text-right">{t("field.received")}</th>
                <th className="text-right">{t("field.available")}</th>
                <th>{t("field.quantity")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {options.map((option) => {
                const key = `${option.work_order_id}:${option.production_batch_id ?? ""}`;
                const busy = manualBusyKey === key;
                return (
                  <tr key={key}>
                    <td>
                      <div className="font-medium text-[#14110b]">{orderLabel(option)}</div>
                      <div className="text-xs text-[#8a8472]">{option.production_no || "-"}</div>
                    </td>
                    <td>{modelLabel(option)}</td>
                    <td>{batchLabel(option)}</td>
                    <td className="text-right tabular-nums">{option.sewing_passed.toLocaleString()}</td>
                    <td className="text-right tabular-nums">{option.received_quantity.toLocaleString()}</td>
                    <td className="text-right font-medium tabular-nums">{option.available_quantity.toLocaleString()}</td>
                    <td>
                      <input
                        className="input w-28"
                        type="number"
                        min={1}
                        max={option.available_quantity}
                        value={quantities[key] ?? option.available_quantity}
                        onChange={(event) => setQuantities((current) => ({
                          ...current,
                          [key]: parseNumberInput(event.target.value),
                        }))}
                      />
                    </td>
                    <td>
                      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => receiveManual(option)}>
                        {busy ? t("page.packagingReceive.receiving") : t("page.packagingReceive.receive")}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!isLoading && options.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-sm text-[#8a8472]">{t("page.packagingReceive.empty")}</td>
                </tr>
              )}
              {isLoading && options.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-sm text-[#8a8472]">{t("common.loading")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card p-4">
        <h2 className="mb-3 text-base font-semibold text-[#14110b]">{t("page.packagingReceive.recentTitle")}</h2>
        <div className="overflow-x-auto">
          <table className="table min-w-[760px]">
            <thead>
              <tr>
                <th>{t("field.date")}</th>
                <th>{t("field.orderNo")}</th>
                <th>{t("field.model")}</th>
                <th>{t("field.batch")}</th>
                <th>{t("field.bundleNo")}</th>
                <th>{t("field.size")}</th>
                <th className="text-right">{t("field.quantity")}</th>
                <th>{t("page.packagingReceive.method")}</th>
              </tr>
            </thead>
            <tbody>
              {receipts.map((receipt) => (
                <tr key={receipt.id}>
                  <td>{new Date(receipt.created_at).toLocaleString()}</td>
                  <td>{orderLabel(receipt)}</td>
                  <td>{modelLabel(receipt)}</td>
                  <td>{batchLabel(receipt)}</td>
                  <td>{receipt.bundle_no || "-"}</td>
                  <td>{receipt.size || "-"}</td>
                  <td className="text-right tabular-nums">{receipt.quantity.toLocaleString()}</td>
                  <td>{t(`page.packagingReceive.method.${receipt.receive_method}`)}</td>
                </tr>
              ))}
              {receipts.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-sm text-[#8a8472]">{t("page.packagingReceive.noReceipts")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
