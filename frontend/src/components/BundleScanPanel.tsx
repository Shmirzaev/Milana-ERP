"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import useSWR from "swr";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  Keyboard,
  Loader2,
  Printer,
  QrCode,
  RefreshCw,
  RotateCcw,
  ScanLine,
  Search,
} from "lucide-react";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import FabricThumbnail from "@/components/FabricThumbnail";
import Modal from "@/components/Modal";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";

type BundleAction = "send-printing" | "receive-printing" | "send-sewing" | "receive-sewing";
type Scope = "all" | "cutting" | "printing" | "sewing";
type Department = { id: number; name: string; code: string };
type SewingFlow = { id: number; name: string; code: string; is_active: boolean };
type SewingBatchResult = {
  production_batch_id: number;
  production_order_id: number;
  production_no?: string | null;
  order_no?: string | null;
  model_code?: string | null;
  batch_label?: string | null;
  bundle_count: number;
  quantity: number;
  assigned_flow_ids?: number[];
  assigned_flow_names?: string[];
  sewing_flow_id?: number;
  sewing_flow_code?: string;
  sewing_flow_name?: string;
  received_count?: number;
  already_accepted?: boolean;
};
type ManualReceiveOption = {
  production_order_id: number;
  model_id: number | null;
  production_no?: string | null;
  order_no?: string | null;
  model_code?: string | null;
  model_name?: string | null;
  material_image_url?: string | null;
  bundle_count: number;
  quantity: number;
};
type ManualReceiveResult = {
  received_count: number;
  received_quantity: number;
  bundle_ids: number[];
};
type MessageTone = "success" | "error" | "info";
type ScanHistoryItem = {
  id: string;
  bundleNo: string;
  model: string;
  status: string;
  time: string;
};

const SEWING_DEPARTMENT_CODES = new Set(["SEW", "MIL", "BST", "ECO"]);

function latestBundleScan(rawCode: string): string {
  const value = rawCode.trimStart();
  const marker = "BUNDLE:";
  const lastBundleMarker = value.toUpperCase().lastIndexOf(marker);
  if (lastBundleMarker > 0) return value.slice(lastBundleMarker);
  return value;
}

function bundleLookupCandidates(rawCode: string): string[] {
  const code = rawCode.trim();
  if (!code) return [];

  const candidates = [code];
  if (code.includes("|")) {
    candidates.push(...code.split("|").map((part) => part.trim()).filter(Boolean));
  }
  if (code.toUpperCase().startsWith("BUNDLE:")) {
    const payload = code.split(":", 2)[1] || "";
    candidates.push(...payload.split("|").map((part) => part.trim()).filter(Boolean));
  }

  return Array.from(new Set(candidates.filter(Boolean)));
}

function sewingBatchIdFromScan(rawCode: string): number | null {
  const code = rawCode.trim();
  if (!code) return null;
  const tokenMatch = code.match(/SEWING_BATCH:(\d+)/i);
  if (tokenMatch) return Number(tokenMatch[1]);
  try {
    const parsed = new URL(code, window.location.origin);
    if (!parsed.pathname.endsWith("/bundles/scan/sewing")) return null;
    const batchId = Number(parsed.searchParams.get("batch") || 0);
    return Number.isInteger(batchId) && batchId > 0 ? batchId : null;
  } catch {
    return null;
  }
}

export default function BundleScanPanel({ scope = "all" }: { scope?: Scope }) {
  const { t } = useT();
  const { me } = useMe();
  const searchParams = useSearchParams();
  const requestedFactory = (searchParams.get("factory") || me?.factory_code || "MIL").toUpperCase();
  const factoryCode = requestedFactory === "BST" || requestedFactory === "ECO" ? requestedFactory : "MIL";
  const { data: departments = [] } = useSWR<Department[]>("/api/departments", fetcher);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const initialBatchHandled = useRef(false);
  const [code, setCode] = useState("");
  const [bundle, setBundle] = useState<any>(null);
  const [sewingBatch, setSewingBatch] = useState<SewingBatchResult | null>(null);
  const [selectedFlowId, setSelectedFlowId] = useState(0);
  const [linePickerOpen, setLinePickerOpen] = useState(false);
  const [linePickerError, setLinePickerError] = useState("");
  const [isAcceptingBatch, setIsAcceptingBatch] = useState(false);
  const [msg, setMsg] = useState("");
  const [messageTone, setMessageTone] = useState<MessageTone>("info");
  const [isLookingUp, setIsLookingUp] = useState(false);
  const [busyAction, setBusyAction] = useState<BundleAction | "">("");
  const [recentScans, setRecentScans] = useState<ScanHistoryItem[]>([]);
  const [manualSearchDraft, setManualSearchDraft] = useState("");
  const [manualSearch, setManualSearch] = useState("");
  const [manualBusyKey, setManualBusyKey] = useState("");
  const [manualMsg, setManualMsg] = useState("");
  const canCuttingScan = can(me, "*", "cutting.bundles");
  const canPrintingScan = can(me, "*", "printing.bundles");
  const canSewingScan = can(me, "*", "sewing.bundles");
  const includeCutting = scope === "all" || scope === "cutting";
  const includePrinting = scope === "all" || scope === "printing";
  const includeSewing = scope === "all" || scope === "sewing";
  const showManualReceive = scope === "sewing" && canSewingScan;
  const { data: sewingFlows = [] } = useSWR<SewingFlow[]>(showManualReceive ? `/api/sewing-flows?factory_code=${factoryCode}` : null, fetcher);
  const departmentById = useMemo(
    () => new Map(departments.map((d) => [Number(d.id), d])),
    [departments],
  );
  const manualReceiveUrl = useMemo(() => {
    const params = new URLSearchParams({ limit: "20" });
    params.set("factory_code", factoryCode);
    if (manualSearch) params.set("q", manualSearch);
    return `/api/bundles/sewing-receive-options?${params.toString()}`;
  }, [manualSearch, factoryCode]);
  const {
    data: manualOptions = [],
    mutate: mutateManualOptions,
    isLoading: manualLoading,
  } = useSWR<ManualReceiveOption[]>(showManualReceive ? manualReceiveUrl : null, fetcher);

  const loadSewingBatch = useCallback(async (batchId: number) => {
    setMsg("");
    setMessageTone("info");
    setBundle(null);
    setSewingBatch(null);
    setLinePickerOpen(false);
    setLinePickerError("");
    setIsLookingUp(true);
    try {
      const result = await api.get<SewingBatchResult>(`/api/bundles/sewing-batches/${batchId}`);
      setSewingBatch(result);
      setSelectedFlowId(result.assigned_flow_ids?.length === 1 ? Number(result.assigned_flow_ids[0]) : 0);
      setLinePickerOpen(true);
    } catch (e: any) {
      setSewingBatch(null);
      setMsg(e.message);
      setMessageTone("error");
      focusScanInput(true);
    } finally {
      setIsLookingUp(false);
    }
  }, []);

  useEffect(() => {
    if (scope !== "sewing" || !canSewingScan || initialBatchHandled.current) return;
    const batchId = sewingBatchIdFromScan(window.location.href);
    if (!batchId) return;
    initialBatchHandled.current = true;
    setCode(window.location.href);
    void loadSewingBatch(batchId);
  }, [canSewingScan, loadSewingBatch, scope]);

  function departmentLabel(id: number | null | undefined) {
    if (!id) return "-";
    const dept = departmentById.get(Number(id));
    return dept ? `${dept.code} - ${dept.name}` : String(id);
  }

  function factoryLabel(value: string | null | undefined) {
    const normalized = String(value || "").trim().toUpperCase();
    if (normalized === "BST" || normalized === "BESTTEX") return t("factory.besttex");
    if (normalized === "ECO" || normalized === "ECO COTTON" || normalized === "ECO_COTTON") return t("factory.ecoCotton");
    return t("factory.milana");
  }

  function focusScanInput(selectText = false) {
    window.setTimeout(() => {
      inputRef.current?.focus();
      if (selectText) inputRef.current?.select();
    }, 0);
  }

  async function acceptSewingBatch() {
    if (!sewingBatch || selectedFlowId <= 0) return;
    setIsAcceptingBatch(true);
    setLinePickerError("");
    try {
      const result = await api.post<SewingBatchResult>(
        `/api/bundles/sewing-batches/${sewingBatch.production_batch_id}/accept`,
        { sewing_flow_id: selectedFlowId },
      );
      setSewingBatch(result);
      setLinePickerOpen(false);
      setCode("");
      setMsg(result.already_accepted
        ? t("page.bundleScan.batchAlreadyAccepted", { batch: result.batch_label || `#${result.production_batch_id}` })
        : t("page.bundleScan.batchAccepted", {
            batch: result.batch_label || `#${result.production_batch_id}`,
            count: result.bundle_count,
            qty: result.quantity,
            line: result.sewing_flow_name || result.sewing_flow_code || `#${selectedFlowId}`,
          }));
      setMessageTone("success");
      await mutateManualOptions();
      focusScanInput();
    } catch (e: any) {
      setLinePickerError(e.message);
    } finally {
      setIsAcceptingBatch(false);
    }
  }

  function rememberBundle(value: any) {
    const item: ScanHistoryItem = {
      id: `${value.id}:${value.status}`,
      bundleNo: String(value.bundle_no || value.id || "-"),
      model: String(value.model_code || value.model_id || "-"),
      status: String(value.status || ""),
      time: t("page.bundleScan.justNow"),
    };
    setRecentScans((current) => [item, ...current.filter((entry) => entry.bundleNo !== item.bundleNo)].slice(0, 5));
  }

  function resetScan() {
    setCode("");
    setBundle(null);
    setSewingBatch(null);
    setSelectedFlowId(0);
    setLinePickerOpen(false);
    setLinePickerError("");
    setMsg("");
    setMessageTone("info");
    focusScanInput();
  }

  async function lookup() {
    setMsg("");
    setMessageTone("info");
    const sewingBatchId = includeSewing ? sewingBatchIdFromScan(code) : null;
    if (sewingBatchId) {
      await loadSewingBatch(sewingBatchId);
      return;
    }
    const candidates = bundleLookupCandidates(code);
    if (!candidates.length) return;
    let lastError = "";
    setIsLookingUp(true);
    try {
      for (const candidate of candidates) {
        try {
          const b = await api.get(`/api/bundles/lookup?code=${encodeURIComponent(candidate)}`);
          setBundle(b);
          setSewingBatch(null);
          setCode(candidate);
          rememberBundle(b);
          focusScanInput(true);
          return;
        } catch (e: any) {
          lastError = e.message;
        }
      }

      const b = await api.get(`/api/bundles/barcode/${encodeURIComponent(candidates[0])}`);
      setBundle(b);
      setSewingBatch(null);
      setCode(candidates[0]);
      rememberBundle(b);
      focusScanInput(true);
    } catch (e: any) {
      setBundle(null);
      setMsg(lastError || e.message);
      setMessageTone("error");
      focusScanInput(true);
    } finally {
      setIsLookingUp(false);
    }
  }

  async function act(action: BundleAction) {
    if (!bundle) return;
    setBusyAction(action);
    setMsg("");
    try {
      const b = await api.post(`/api/bundles/${bundle.id}/${action}`);
      setBundle(b);
      setCode("");
      setMsg(t("msg.saved"));
      setMessageTone("success");
      rememberBundle(b);
      focusScanInput();
    } catch (e: any) {
      setMsg(e.message);
      setMessageTone("error");
      focusScanInput(true);
    } finally {
      setBusyAction("");
    }
  }

  function submitManualSearch(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setManualSearch(manualSearchDraft.trim());
  }

  async function manualReceive(option: ManualReceiveOption) {
    const key = `${option.production_order_id}:${option.model_id ?? ""}`;
    setManualBusyKey(key);
    setManualMsg("");
    try {
      const result = await api.post<ManualReceiveResult>("/api/bundles/manual-receive-sewing", {
        production_order_id: option.production_order_id,
        model_id: option.model_id,
        factory_code: factoryCode,
      });
      const order = option.order_no || option.production_no || `#${option.production_order_id}`;
      setManualMsg(t("page.bundleScan.manualReceived", {
        count: result.received_count,
        qty: result.received_quantity,
        order,
      }));
      if (bundle && result.bundle_ids.includes(Number(bundle.id))) {
        setBundle(null);
        setCode("");
      }
      await mutateManualOptions();
      focusScanInput();
    } catch (e: any) {
      setManualMsg(e.message);
    } finally {
      setManualBusyKey("");
    }
  }

  const nextDept = bundle?.next_department_id ? departmentById.get(Number(bundle.next_department_id)) : null;
  const nextDeptCode = String(nextDept?.code || "").toUpperCase();
  const selectedFactory = factoryLabel(bundle?.sewing_factory_code || nextDeptCode);
  const nextIsSewingFactory = SEWING_DEPARTMENT_CODES.has(nextDeptCode);
  const canReceiveBundle = canSewingScan && Boolean(
    me && bundle && String(bundle.sewing_factory_code || "MIL").trim().toUpperCase() === me.factory_code,
  );
  const scopeTitle = t(`page.bundleScan.${scope}Title`);
  const scopeSubtitle = t(`page.bundleScan.${scope}Subtitle`);
  const scanState = isLookingUp ? "loading" : bundle || sewingBatch ? "success" : messageTone === "error" && msg ? "error" : "ready";

  const availableActions: Array<{ key: BundleAction; label: string; primary?: boolean }> = [];
  if (bundle?.status === "created" && canCuttingScan && includeCutting) {
    if (nextDeptCode === "PRT") {
      availableActions.push({ key: "send-printing", label: t("btn.sendToPrinting"), primary: true });
    } else {
      availableActions.push({ key: "send-sewing", label: t("btn.sendToFactory", { factory: selectedFactory }), primary: true });
    }
  }
  if (bundle?.status === "sent_to_printing" && canPrintingScan && includePrinting) {
    availableActions.push({ key: "receive-printing", label: t("btn.receiveAtPrinting"), primary: true });
  }
  if (bundle?.status === "received_printing" && canPrintingScan && includePrinting) {
    availableActions.push({ key: "send-sewing", label: t("btn.sendToFactory", { factory: selectedFactory }), primary: true });
  }
  if (bundle?.status === "created" && canReceiveBundle && includeSewing && nextIsSewingFactory) {
    availableActions.push({ key: "receive-sewing", label: t("btn.receiveAtFactory", { factory: selectedFactory }), primary: true });
  }
  if (bundle?.status === "sent_to_sewing" && canReceiveBundle && includeSewing) {
    availableActions.push({ key: "receive-sewing", label: t("btn.receiveAtFactory", { factory: selectedFactory }), primary: true });
  }

  return (
    <div>
      <PageHeader title={scopeTitle} subtitle={scopeSubtitle} />

      <section className="scan-workspace" aria-label={scopeTitle}>
        <div className="scan-entry">
          <div className="scan-entry-header">
            <div className={`scan-status scan-status--${scanState}`} aria-live="polite">
              {scanState === "loading" ? <Loader2 className="animate-spin" /> : null}
              {scanState === "success" ? <CheckCircle2 /> : null}
              {scanState === "error" ? <AlertCircle /> : null}
              {scanState === "ready" ? <ScanLine /> : null}
              <span>
                {scanState === "loading"
                  ? t("page.bundleScan.lookingUp")
                  : scanState === "success"
                    ? t(sewingBatch ? "page.bundleScan.batchFound" : "page.bundleScan.bundleFound")
                    : scanState === "error"
                      ? t("page.bundleScan.scanFailed")
                      : t("page.bundleScan.ready")}
              </span>
            </div>
            {(bundle || sewingBatch || msg) && (
              <button type="button" className="btn btn-ghost" onClick={resetScan}>
                <RotateCcw />
                {t("page.bundleScan.newScan")}
              </button>
            )}
          </div>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              void lookup();
            }}
          >
            <label className="scan-field-label" htmlFor={`bundle-scan-${scope}`}>
              {t(showManualReceive ? "page.bundleScan.batchOrBundleField" : "page.bundleScan.scanField")}
            </label>
            <div className="scan-input-row">
              <div className="scan-input-wrap">
                <QrCode className="scan-input-icon" />
                <input
                  id={`bundle-scan-${scope}`}
                  ref={inputRef}
                  className="input scan-input"
                  autoComplete="off"
                  autoFocus
                  inputMode="text"
                  placeholder={t(showManualReceive ? "page.bundleScan.batchOrBundlePlaceholder" : "ph.bundleBarcode")}
                  value={code}
                  onChange={(event) => {
                    setCode(latestBundleScan(event.target.value));
                    if (msg) setMsg("");
                  }}
                  onFocus={(event) => event.currentTarget.select()}
                  onClick={(event) => event.currentTarget.select()}
                />
                <span className="scan-enter-hint" aria-hidden="true">
                  <Keyboard />
                  {t("common.enter")}
                </span>
              </div>
              <button className="btn btn-primary scan-lookup" type="submit" disabled={isLookingUp || !code.trim()}>
                {isLookingUp ? <Loader2 className="animate-spin" /> : <Search />}
                {isLookingUp ? t("page.bundleScan.lookingUp") : t("btn.lookup")}
              </button>
            </div>
          </form>

          {msg && (
            <div className={`scan-message scan-message--${messageTone}`} role={messageTone === "error" ? "alert" : "status"}>
              {messageTone === "error" ? <AlertCircle /> : <CheckCircle2 />}
              <span>{msg}</span>
            </div>
          )}
        </div>

        {sewingBatch ? (
          <div className="scan-result">
            <div className="scan-result-header">
              <div>
                <div className="scan-result-label">{t("field.batch")}</div>
                <div className="scan-result-number">{sewingBatch.batch_label || `#${sewingBatch.production_batch_id}`}</div>
              </div>
              <span className="badge">
                {sewingBatch.sewing_flow_id
                  ? t("page.bundleScan.batchAcceptedStatus")
                  : t("page.bundleScan.batchReadyStatus")}
              </span>
            </div>

            <dl className="scan-detail-grid">
              <div>
                <dt>{t("field.orderNo")}</dt>
                <dd>{sewingBatch.order_no || sewingBatch.production_no || `#${sewingBatch.production_order_id}`}</dd>
              </div>
              <div>
                <dt>{t("field.model")}</dt>
                <dd>{sewingBatch.model_code || "-"}</dd>
              </div>
              <div>
                <dt>{t("nav.bundles")}</dt>
                <dd>{sewingBatch.bundle_count}</dd>
              </div>
              <div>
                <dt>{t("field.quantity")}</dt>
                <dd>{t("page.bundleScan.pieces", { count: sewingBatch.quantity })}</dd>
              </div>
              <div>
                <dt>{t("page.bundleScan.sewingLine")}</dt>
                <dd>
                  {sewingBatch.sewing_flow_name
                    || sewingBatch.assigned_flow_names?.join(", ")
                    || t("page.bundleScan.notAssigned")}
                </dd>
              </div>
            </dl>

            {!sewingBatch.sewing_flow_id && (
              <div className="scan-actions">
                <button
                  type="button"
                  className="btn btn-primary scan-action"
                  onClick={() => setLinePickerOpen(true)}
                >
                  <CheckCircle2 />
                  {t("page.bundleScan.selectSewingLine")}
                </button>
              </div>
            )}
          </div>
        ) : bundle ? (
          <div className="scan-result">
            <div className="scan-result-header">
              <div>
                <div className="scan-result-label">{t("field.bundleNo")}</div>
                <div className="scan-result-number">{bundle.bundle_no}</div>
              </div>
              <span className="badge">{statusLabel(bundle.status, t)}</span>
            </div>

            <dl className="scan-detail-grid">
              <div>
                <dt>{t("field.model")}</dt>
                <dd>{bundle.model_code || bundle.model_id || "-"}</dd>
              </div>
              <div>
                <dt>{t("field.color")} / {t("field.size")}</dt>
                <dd>{bundle.color || "-"} / {bundle.size || "-"}</dd>
              </div>
              <div>
                <dt>{t("field.quantity")}</dt>
                <dd>{t("page.bundleScan.pieces", { count: bundle.quantity ?? 0 })}</dd>
              </div>
              <div>
                <dt>{t("field.batch")}</dt>
                <dd>{bundle.batch_label || "-"}</dd>
              </div>
            </dl>

            {bundle.tracking_passport_no && (
              <div className="scan-passport">
                <span>{t("field.trackingPassport")}</span>
                <strong>{bundle.tracking_passport_no}</strong>
              </div>
            )}

            <div className="scan-route">
              <div>
                <span>{t("field.currentDept")}</span>
                <strong>{departmentLabel(bundle.current_department_id)}</strong>
              </div>
              <ArrowRight aria-hidden="true" />
              <div>
                <span>{t("field.nextDept")}</span>
                <strong>{departmentLabel(bundle.next_department_id)}</strong>
              </div>
            </div>

            <div className="scan-actions">
              {availableActions.map((action) => (
                <button
                  key={action.key}
                  className={`btn scan-action ${action.primary ? "btn-primary" : ""}`}
                  disabled={Boolean(busyAction)}
                  onClick={() => void act(action.key)}
                  type="button"
                >
                  {busyAction === action.key ? <Loader2 className="animate-spin" /> : <ArrowRight />}
                  {busyAction === action.key ? t("page.bundleScan.updating") : action.label}
                </button>
              ))}
              {availableActions.length === 0 && <div className="scan-no-actions">{t("page.bundleScan.noActions")}</div>}
              <button
                type="button"
                className="btn scan-print"
                onClick={() => api.openLabel(`/api/bundles/${bundle.id}/label`)}
              >
                <Printer />
                {t("btn.printLabel")}
              </button>
            </div>
          </div>
        ) : (
          <div className="scan-empty">
            <QrCode />
            <strong>{t(showManualReceive ? "page.bundleScan.waitingBatchTitle" : "page.bundleScan.waitingTitle")}</strong>
            <span>{t(showManualReceive ? "page.bundleScan.waitingBatchSubtitle" : "page.bundleScan.waitingSubtitle")}</span>
          </div>
        )}
      </section>

      {recentScans.length > 0 && (
        <section className="scan-history" aria-labelledby="recent-scans-title">
          <div className="scan-history-header">
            <div>
              <h2 id="recent-scans-title">{t("page.bundleScan.recentTitle")}</h2>
              <p>{t("page.bundleScan.recentSubtitle")}</p>
            </div>
            <button type="button" className="btn btn-ghost" onClick={() => setRecentScans([])}>
              {t("common.clear")}
            </button>
          </div>
          <div className="scan-history-list">
            {recentScans.map((item) => (
              <div className="scan-history-row" key={item.id}>
                <QrCode />
                <div>
                  <strong>{item.bundleNo}</strong>
                  <span>{item.model} · {statusLabel(item.status, t)}</span>
                </div>
                <time>{item.time}</time>
              </div>
            ))}
          </div>
        </section>
      )}

      {showManualReceive && (
        <div className="card mt-4 max-w-4xl p-4">
          <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">{t("page.bundleScan.manualTitle")}</h2>
              <p className="mt-1 text-sm text-slate-500">{t("page.bundleScan.manualSubtitle")}</p>
            </div>
            <button type="button" className="btn shrink-0" onClick={() => mutateManualOptions()}>
              <RefreshCw className="h-4 w-4" />
              {t("btn.refresh")}
            </button>
          </div>

          <form className="mb-3 flex flex-col gap-2 sm:flex-row" onSubmit={submitManualSearch}>
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                className="input pl-9"
                value={manualSearchDraft}
                onChange={(event) => setManualSearchDraft(event.target.value)}
                placeholder={t("page.bundleScan.manualSearchPlaceholder")}
              />
            </div>
            <button type="submit" className="btn btn-primary">{t("common.search")}</button>
          </form>

          {manualMsg && <div className="mb-3 text-sm">{manualMsg}</div>}

          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("field.model")}</th>
                  <th>{t("nav.bundles")}</th>
                  <th>{t("field.qty")}</th>
                  <th>{t("field.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {manualLoading && manualOptions.length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-slate-500">{t("common.loading")}</td>
                  </tr>
                )}
                {!manualLoading && manualOptions.length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-slate-500">{t("page.bundleScan.manualEmpty")}</td>
                  </tr>
                )}
                {manualOptions.map((option) => {
                  const key = `${option.production_order_id}:${option.model_id ?? ""}`;
                  const busy = manualBusyKey === key;
                  return (
                    <tr key={key}>
                      <td>
                        <div className="font-medium">{option.order_no || option.production_no || `#${option.production_order_id}`}</div>
                        {option.production_no && option.production_no !== option.order_no && (
                          <div className="text-xs text-slate-500">{option.production_no}</div>
                        )}
                      </td>
                      <td>
                        <div className="flex min-w-[190px] items-center gap-3">
                          <FabricThumbnail
                            imageUrl={option.material_image_url}
                            label={option.model_code || option.model_name}
                          />
                          <div className="min-w-0">
                            <div className="font-medium">{option.model_code || option.model_id || "-"}</div>
                            {option.model_name && <div className="truncate text-xs text-slate-500">{option.model_name}</div>}
                          </div>
                        </div>
                      </td>
                      <td>{option.bundle_count}</td>
                      <td>{option.quantity}</td>
                      <td>
                        <button
                          type="button"
                          className="btn btn-primary"
                          disabled={busy}
                          onClick={() => manualReceive(option)}
                        >
                          <CheckCircle2 className="h-4 w-4" />
                          {busy ? t("page.bundleScan.manualReceiving") : t("page.bundleScan.manualReceive")}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <Modal
        open={linePickerOpen && Boolean(sewingBatch)}
        onClose={() => {
          if (isAcceptingBatch) return;
          setLinePickerOpen(false);
          setLinePickerError("");
          focusScanInput(true);
        }}
        title={t("page.bundleScan.chooseLineForBatch")}
        closeOnOutsideClick={!isAcceptingBatch}
      >
        {sewingBatch && (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void acceptSewingBatch();
            }}
          >
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-[var(--erp-border)] pb-4 text-sm">
              <div>
                <dt className="text-[var(--erp-text-muted)]">{t("field.batch")}</dt>
                <dd className="font-medium text-[var(--erp-text)]">{sewingBatch.batch_label || `#${sewingBatch.production_batch_id}`}</dd>
              </div>
              <div>
                <dt className="text-[var(--erp-text-muted)]">{t("field.orderNo")}</dt>
                <dd className="font-medium text-[var(--erp-text)]">{sewingBatch.order_no || sewingBatch.production_no || `#${sewingBatch.production_order_id}`}</dd>
              </div>
              <div>
                <dt className="text-[var(--erp-text-muted)]">{t("field.model")}</dt>
                <dd className="font-medium text-[var(--erp-text)]">{sewingBatch.model_code || "-"}</dd>
              </div>
              <div>
                <dt className="text-[var(--erp-text-muted)]">{t("nav.bundles")}</dt>
                <dd className="font-medium text-[var(--erp-text)]">
                  {sewingBatch.bundle_count} · {t("page.bundleScan.pieces", { count: sewingBatch.quantity })}
                </dd>
              </div>
            </dl>

            <div>
              <label className="label" htmlFor="sewing-batch-line-picker">
                {t("page.bundleScan.sewingLine")}
              </label>
              <select
                id="sewing-batch-line-picker"
                className="input"
                value={selectedFlowId || ""}
                onChange={(event) => {
                  setSelectedFlowId(Number(event.target.value || 0));
                  setLinePickerError("");
                }}
                disabled={isAcceptingBatch || sewingFlows.length === 0}
                autoFocus
                required
              >
                <option value="">
                  {sewingFlows.length > 0
                    ? t("page.bundleScan.selectSewingLine")
                    : t("page.bundleScan.noSewingLines")}
                </option>
                {sewingFlows.map((flow) => (
                  <option key={flow.id} value={flow.id}>{flow.code} - {flow.name}</option>
                ))}
              </select>
              <p className="mt-2 text-sm text-[var(--erp-text-muted)]">{t("page.bundleScan.acceptAndAssignHint")}</p>
            </div>

            {linePickerError && (
              <div className="scan-message scan-message--error" role="alert">
                <AlertCircle />
                <span>{linePickerError}</span>
              </div>
            )}

            <div className="flex justify-end gap-2 border-t border-[var(--erp-border)] pt-4">
              <button
                type="button"
                className="btn"
                disabled={isAcceptingBatch}
                onClick={() => {
                  setLinePickerOpen(false);
                  setLinePickerError("");
                  focusScanInput(true);
                }}
              >
                {t("common.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={selectedFlowId <= 0 || isAcceptingBatch}
              >
                {isAcceptingBatch ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                {isAcceptingBatch ? t("page.bundleScan.updating") : t("page.bundleScan.acceptAndAssignBatch")}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
