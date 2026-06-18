"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Calculator,
  Download,
  RefreshCw,
  ScanLine,
  Trash2,
  UserCheck,
} from "lucide-react";
import PageHeader from "@/components/PageHeader";

type EmployeePayload = {
  v?: number;
  type: "employee_payroll";
  source?: string;
  badge_id?: string | null;
  employee_id: number;
  user_id?: number | null;
  employee_name: string;
  department_id?: number | null;
  department_name?: string | null;
  position?: string | null;
  status?: string | null;
  issued_at?: string | null;
  copy_index?: number | null;
};

type WorkPayload = {
  v?: number;
  type: "process_payroll";
  source?: string;
  label_id?: string | null;
  production_order_id?: number | null;
  production_no?: string | null;
  sales_order_id?: number | null;
  sales_order_no?: string | null;
  batch_id?: number | null;
  batch_key?: string | null;
  batch_no?: string | null;
  batch_index?: number | null;
  model_id?: number | null;
  model_code?: string | null;
  operation_section?: string | null;
  operation_code?: string | null;
  operation_name?: string | null;
  quantity?: number | null;
  rate_per_piece?: number | null;
  currency?: string | null;
  payroll_unit?: string | null;
  issued_at?: string | null;
  copy_index?: number | null;
};

type PayrollRecord = {
  id: string;
  scannedAt: string;
  employeeId: number;
  employeeName: string;
  departmentName: string;
  position: string;
  workKey: string;
  productionNo: string;
  salesOrderNo: string;
  batchNo: string;
  modelCode: string;
  operationSection: string;
  operationCode: string;
  operationName: string;
  quantity: number;
  ratePerPiece: number;
  currency: string;
  rawEmployee: EmployeePayload;
  rawWork: WorkPayload;
};

type EmployeeSummary = {
  employeeId: number;
  employeeName: string;
  departmentName: string;
  position: string;
  quantity: number;
  totalPay: number;
  currency: string;
  records: PayrollRecord[];
};

type OperationSummary = {
  key: string;
  label: string;
  quantity: number;
  totalPay: number;
  currency: string;
};

type PayrollSessionStats = {
  employeeSummaries: EmployeeSummary[];
  recordsByEmployee: Map<number, PayrollRecord[]>;
  quantity: number;
  pay: number;
  currency: string;
};

const STORAGE_KEY = "milana_payroll_scan_records_v2";
const LEGACY_STORAGE_KEYS = ["milana_payroll_scan_records_v1"];
const EMPTY_RECORDS: PayrollRecord[] = [];
const HISTORY_RENDER_LIMIT = 100;
const AUTO_SUBMIT_DELAY_MS = 140;

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function numberOrZero(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function formatMoney(value: number, currency: string): string {
  if (!value) return `0 ${currency || ""}`.trim();
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency || ""}`.trim();
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function optionalNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function optionalString(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text || null;
}

function compactField(value: string | undefined): string | null {
  const text = String(value || "").trim();
  return text && text !== "-" ? text : null;
}

function compactNumberField(value: string | undefined): number | null {
  const text = compactField(value);
  if (text == null) return null;
  return optionalNumber(text);
}

function parseCompactScanPayload(value: string): EmployeePayload | WorkPayload | null {
  const parts = value.trim().split("*");
  const kind = String(parts[0] || "").toUpperCase();

  if (kind === "ME2") {
    const employeeId = compactNumberField(parts[1]);
    if (employeeId == null) return null;
    return {
      type: "employee_payroll",
      source: "milana_erp_compact",
      badge_id: ["EMP", employeeId, compactField(parts[8]) || 1].join(":"),
      employee_id: employeeId,
      user_id: compactNumberField(parts[2]),
      employee_name: compactField(parts[3]) || `Employee ${employeeId}`,
      department_id: compactNumberField(parts[4]),
      department_name: compactField(parts[5]),
      position: compactField(parts[6]),
      status: compactField(parts[7]),
      copy_index: compactNumberField(parts[8]),
    };
  }

  if (kind === "MW2") {
    return {
      type: "process_payroll",
      source: "milana_erp_compact",
      production_order_id: compactNumberField(parts[1]),
      production_no: compactField(parts[2]),
      batch_id: compactNumberField(parts[3]),
      batch_no: compactField(parts[4]),
      batch_index: compactNumberField(parts[5]),
      model_code: compactField(parts[6]),
      operation_section: compactField(parts[7]),
      operation_code: compactField(parts[8]),
      operation_name: compactField(parts[9]),
      quantity: compactNumberField(parts[10]),
      rate_per_piece: compactNumberField(parts[11]),
      currency: compactField(parts[12]) || "UZS",
      payroll_unit: "piece",
      copy_index: compactNumberField(parts[13]),
    };
  }

  return null;
}

function normalizeScanPayload(value: unknown): EmployeePayload | WorkPayload | null {
  const parsed = asObject(value);
  if (!parsed) return null;

  if (parsed.type === "employee_payroll" || parsed.type === "process_payroll") {
    return parsed as EmployeePayload | WorkPayload;
  }

  if (parsed.t === "e") {
    const employeeId = optionalNumber(parsed.e ?? parsed.employee_id);
    if (employeeId == null) return null;
    return {
      v: optionalNumber(parsed.v) ?? undefined,
      type: "employee_payroll",
      source: optionalString(parsed.src) || "milana_erp",
      badge_id: optionalString(parsed.id ?? parsed.badge_id),
      employee_id: employeeId,
      user_id: optionalNumber(parsed.u ?? parsed.user_id),
      employee_name: optionalString(parsed.n ?? parsed.employee_name) || `Employee ${employeeId}`,
      department_id: optionalNumber(parsed.did ?? parsed.department_id),
      department_name: optionalString(parsed.d ?? parsed.department_name),
      position: optionalString(parsed.p ?? parsed.position),
      status: optionalString(parsed.s ?? parsed.status),
      copy_index: optionalNumber(parsed.ci ?? parsed.copy_index),
    };
  }

  if (parsed.t === "w") {
    return {
      v: optionalNumber(parsed.v) ?? undefined,
      type: "process_payroll",
      source: optionalString(parsed.src) || "milana_erp",
      label_id: optionalString(parsed.id ?? parsed.label_id),
      production_order_id: optionalNumber(parsed.pid ?? parsed.production_order_id),
      production_no: optionalString(parsed.po ?? parsed.production_no),
      sales_order_id: optionalNumber(parsed.soid ?? parsed.sales_order_id),
      sales_order_no: optionalString(parsed.so ?? parsed.sales_order_no),
      batch_id: optionalNumber(parsed.bi ?? parsed.batch_id),
      batch_key: optionalString(parsed.bk ?? parsed.batch_key),
      batch_no: optionalString(parsed.b ?? parsed.batch_no),
      batch_index: optionalNumber(parsed.bx ?? parsed.batch_index),
      model_id: optionalNumber(parsed.mid ?? parsed.model_id),
      model_code: optionalString(parsed.m ?? parsed.model_code),
      operation_section: optionalString(parsed.s ?? parsed.operation_section),
      operation_code: optionalString(parsed.oc ?? parsed.operation_code),
      operation_name: optionalString(parsed.on ?? parsed.operation_name),
      quantity: optionalNumber(parsed.q ?? parsed.quantity),
      rate_per_piece: optionalNumber(parsed.r ?? parsed.rate_per_piece),
      currency: optionalString(parsed.c ?? parsed.currency) || "UZS",
      payroll_unit: "piece",
      copy_index: optionalNumber(parsed.ci ?? parsed.copy_index),
    };
  }

  return null;
}

function parseScanPayload(raw: string): EmployeePayload | WorkPayload {
  const trimmed = raw.replace(/[\u0000-\u001f\u007f]/g, "").trim();
  if (!trimmed) throw new Error("Scan is empty.");

  const candidates: string[] = [];
  addCandidate(candidates, trimmed);

  for (const candidate of [...candidates]) {
    try {
      const url = new URL(candidate);
      for (const key of ["payload", "data", "qr"]) {
        addCandidate(candidates, url.searchParams.get(key));
      }
    } catch {}
  }

  for (const candidate of [...candidates]) {
    let decoded = candidate;
    for (let i = 0; i < 3; i += 1) {
      try {
        const nextDecoded = decodeURIComponent(decoded);
        if (nextDecoded === decoded) break;
        decoded = nextDecoded;
        addCandidate(candidates, decoded);
      } catch {
        break;
      }
    }
  }

  for (const candidate of [...candidates]) {
    const firstBrace = candidate.indexOf("{");
    const lastBrace = candidate.lastIndexOf("}");
    if (firstBrace >= 0 && lastBrace > firstBrace) {
      addCandidate(candidates, candidate.slice(firstBrace, lastBrace + 1));
    }
  }

  for (const candidate of candidates) {
    const parsed = parseCompactScanPayload(candidate);
    if (parsed) return parsed;
  }

  for (const candidate of candidates) {
    try {
      const parsed = normalizeScanPayload(JSON.parse(candidate));
      if (parsed) return parsed;
    } catch {}
  }

  throw new Error("Unknown QR. Scan an employee or process payroll QR.");
}

function buildWorkKey(payload: WorkPayload): string {
  if (payload.label_id) return String(payload.label_id).trim();
  return [
    payload.production_order_id || payload.production_no || "po",
    payload.batch_id || payload.batch_key || payload.batch_no || "batch",
    payload.operation_code || payload.operation_name || "operation",
    payload.copy_index || 1,
  ]
    .map((part) => String(part).trim())
    .join("|");
}

function toPayrollRecord(employee: EmployeePayload, work: WorkPayload): PayrollRecord {
  const quantity = Math.max(0, numberOrZero(work.quantity));
  const ratePerPiece = Math.max(0, numberOrZero(work.rate_per_piece));
  const currency = String(work.currency || "UZS").trim().toUpperCase();
  return {
    id: newId(),
    scannedAt: new Date().toISOString(),
    employeeId: Number(employee.employee_id),
    employeeName: String(employee.employee_name || `Employee ${employee.employee_id}`),
    departmentName: String(employee.department_name || "-"),
    position: String(employee.position || "-"),
    workKey: buildWorkKey(work),
    productionNo: String(work.production_no || work.production_order_id || "-"),
    salesOrderNo: String(work.sales_order_no || work.sales_order_id || "-"),
    batchNo: String(work.batch_no || work.batch_key || "-"),
    modelCode: String(work.model_code || work.model_id || "-"),
    operationSection: String(work.operation_section || "-"),
    operationCode: String(work.operation_code || "-"),
    operationName: String(work.operation_name || work.operation_code || "-"),
    quantity,
    ratePerPiece,
    currency,
    rawEmployee: employee,
    rawWork: work,
  };
}

function csvEscape(value: unknown): string {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replaceAll("\"", "\"\"")}"`;
  return text;
}

function addCandidate(candidates: string[], value: string | null | undefined) {
  const text = String(value || "").trim();
  if (text && !candidates.includes(text)) candidates.push(text);
}

function buildRecordByWorkKey(records: PayrollRecord[]): Map<string, PayrollRecord> {
  const map = new Map<string, PayrollRecord>();
  for (const record of records) {
    if (!map.has(record.workKey)) map.set(record.workKey, record);
  }
  return map;
}

function looksCompleteScan(value: string): boolean {
  const text = value.trim();
  if (text.length < 12) return false;
  if (/^M[EW]2\*/i.test(text)) return true;
  if (text.startsWith("{") && text.endsWith("}")) return true;
  const lower = text.toLowerCase();
  if (lower.includes("%7b") && lower.includes("%7d")) return true;
  if (/^https?:\/\//i.test(text) && /[?&](payload|data|qr)=/.test(text)) return true;
  return false;
}

export default function PayrollScanPage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const recordsRef = useRef<PayrollRecord[]>([]);
  const currentEmployeeRef = useRef<EmployeePayload | null>(null);
  const workRecordByKeyRef = useRef<Map<string, PayrollRecord>>(new Map());
  const autoSubmitTimerRef = useRef<number | null>(null);
  const inputHasTextRef = useRef(false);
  const lastScanRef = useRef<{ raw: string; at: number } | null>(null);
  const [inputHasText, setInputHasText] = useState(false);
  const [currentEmployee, setCurrentEmployee] = useState<EmployeePayload | null>(null);
  const [records, setRecords] = useState<PayrollRecord[]>([]);
  const [recordsLoaded, setRecordsLoaded] = useState(false);
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"info" | "success" | "warning" | "error">("info");

  useEffect(() => {
    try {
      for (const key of LEGACY_STORAGE_KEYS) {
        localStorage.removeItem(key);
      }
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          recordsRef.current = parsed;
          workRecordByKeyRef.current = buildRecordByWorkKey(parsed);
          setRecords(parsed);
        }
      }
    } catch {}
    setRecordsLoaded(true);
  }, []);

  useEffect(() => {
    recordsRef.current = records;
    workRecordByKeyRef.current = buildRecordByWorkKey(records);
  }, [records]);

  useEffect(() => {
    if (!recordsLoaded) return;
    const timeout = window.setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
      } catch {}
    }, 250);

    return () => window.clearTimeout(timeout);
  }, [records, recordsLoaded]);

  useEffect(() => {
    if (!recordsLoaded) return;
    const flushRecords = () => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(recordsRef.current));
      } catch {}
    };
    window.addEventListener("pagehide", flushRecords);
    window.addEventListener("beforeunload", flushRecords);
    return () => {
      window.removeEventListener("pagehide", flushRecords);
      window.removeEventListener("beforeunload", flushRecords);
    };
  }, [recordsLoaded]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [currentEmployee, records.length]);

  useEffect(() => {
    currentEmployeeRef.current = currentEmployee;
  }, [currentEmployee]);

  useEffect(() => () => {
    if (autoSubmitTimerRef.current != null) {
      window.clearTimeout(autoSubmitTimerRef.current);
    }
  }, []);

  const currentEmployeeId = currentEmployee ? Number(currentEmployee.employee_id) : null;

  useEffect(() => {
    setShowAllHistory(false);
  }, [currentEmployeeId]);

  const sessionStats = useMemo<PayrollSessionStats>(() => {
    const employeeMap = new Map<number, EmployeeSummary>();
    let quantity = 0;
    let pay = 0;
    let currency = records[0]?.currency || "UZS";

    for (const record of records) {
      quantity += record.quantity;
      pay += record.quantity * record.ratePerPiece;
      currency = currency || record.currency || "UZS";

      const current = employeeMap.get(record.employeeId) || {
        employeeId: record.employeeId,
        employeeName: record.employeeName,
        departmentName: record.departmentName,
        position: record.position,
        quantity: 0,
        totalPay: 0,
        currency: record.currency,
        records: [],
      };
      current.quantity += record.quantity;
      current.totalPay += record.quantity * record.ratePerPiece;
      current.records.push(record);
      employeeMap.set(record.employeeId, current);
    }

    const employeeSummaries = Array.from(employeeMap.values()).sort((a, b) => b.totalPay - a.totalPay);
    return {
      employeeSummaries,
      recordsByEmployee: new Map(employeeSummaries.map((summary) => [summary.employeeId, summary.records])),
      quantity,
      pay,
      currency,
    };
  }, [records]);

  const employeeSummaries = sessionStats.employeeSummaries;
  const visibleRecords = currentEmployeeId == null
    ? EMPTY_RECORDS
    : sessionStats.recordsByEmployee.get(currentEmployeeId) || EMPTY_RECORDS;
  const visibleHistoryRows = useMemo(
    () => (showAllHistory ? visibleRecords : visibleRecords.slice(0, HISTORY_RENDER_LIMIT)),
    [showAllHistory, visibleRecords],
  );
  const hiddenHistoryCount = Math.max(0, visibleRecords.length - visibleHistoryRows.length);

  const operationSummaries = useMemo<OperationSummary[]>(() => {
    const map = new Map<string, OperationSummary>();
    for (const record of visibleRecords) {
      const key = `${record.operationSection}|${record.operationCode}`;
      const current = map.get(key) || {
        key,
        label: `${record.operationName} (${record.operationCode})`,
        quantity: 0,
        totalPay: 0,
        currency: record.currency,
      };
      current.quantity += record.quantity;
      current.totalPay += record.quantity * record.ratePerPiece;
      map.set(key, current);
    }
    return Array.from(map.values()).sort((a, b) => b.quantity - a.quantity);
  }, [visibleRecords]);

  const totals = {
    quantity: sessionStats.quantity,
    pay: sessionStats.pay,
    currency: sessionStats.currency,
  };

  function setNotice(text: string, tone: typeof messageTone = "info") {
    setMessage(text);
    setMessageTone(tone);
  }

  function clearAutoSubmitTimer() {
    if (autoSubmitTimerRef.current != null) {
      window.clearTimeout(autoSubmitTimerRef.current);
      autoSubmitTimerRef.current = null;
    }
  }

  function setInputHasTextState(hasText: boolean) {
    if (inputHasTextRef.current === hasText) return;
    inputHasTextRef.current = hasText;
    setInputHasText(hasText);
  }

  function clearScanInput() {
    clearAutoSubmitTimer();
    if (inputRef.current) {
      inputRef.current.value = "";
      inputRef.current.focus();
    }
    setInputHasTextState(false);
  }

  function selectEmployee(payload: EmployeePayload) {
    currentEmployeeRef.current = payload;
    setCurrentEmployee(payload);
  }

  function replaceRecords(nextRecords: PayrollRecord[]) {
    recordsRef.current = nextRecords;
    workRecordByKeyRef.current = buildRecordByWorkKey(nextRecords);
    setRecords(nextRecords);
  }

  function addRecord(record: PayrollRecord) {
    const nextRecords = [record, ...recordsRef.current];
    recordsRef.current = nextRecords;
    workRecordByKeyRef.current.set(record.workKey, record);
    setRecords(nextRecords);
  }

  function handleScanInput(event: React.ChangeEvent<HTMLInputElement>) {
    const value = event.currentTarget.value;
    setInputHasTextState(Boolean(value.trim()));
    clearAutoSubmitTimer();
    if (looksCompleteScan(value)) {
      autoSubmitTimerRef.current = window.setTimeout(() => submitScan(), AUTO_SUBMIT_DELAY_MS);
    }
  }

  function submitScan(event?: React.FormEvent) {
    event?.preventDefault();
    clearAutoSubmitTimer();
    const raw = inputRef.current?.value.trim() || "";
    if (!raw) return;
    clearScanInput();

    const now = Date.now();
    const lastScan = lastScanRef.current;
    if (lastScan && lastScan.raw === raw && now - lastScan.at < 700) return;
    lastScanRef.current = { raw, at: now };

    try {
      const payload = parseScanPayload(raw);
      if (payload.type === "employee_payroll") {
        selectEmployee(payload);
        setNotice(`Employee selected: ${payload.employee_name}`, "success");
        return;
      }

      const workKey = buildWorkKey(payload);
      const existingWorkRecord = workRecordByKeyRef.current.get(workKey);
      if (existingWorkRecord) {
        setNotice(
          `This work QR is already in ${existingWorkRecord.employeeName}'s paycheck. It cannot be counted twice.`,
          "warning",
        );
        return;
      }

      const employee = currentEmployeeRef.current;
      if (!employee) {
        setNotice("Scan an employee QR first.", "warning");
        return;
      }

      const nextRecord = toPayrollRecord(employee, payload);
      addRecord(nextRecord);
      setNotice(
        `Added ${nextRecord.quantity.toLocaleString()} pcs for ${nextRecord.employeeName}.`,
        "success",
      );
    } catch (error: any) {
      setNotice(error?.message || "Could not read QR.", "error");
    }
  }

  function updateRecord(id: string, patch: Partial<PayrollRecord>) {
    replaceRecords(recordsRef.current.map((record) => (record.id === id ? { ...record, ...patch } : record)));
  }

  function removeRecord(id: string) {
    replaceRecords(recordsRef.current.filter((record) => record.id !== id));
  }

  function clearRecords() {
    if (!records.length) return;
    if (!confirm("Clear current payroll scan session?")) return;
    replaceRecords([]);
    setNotice("Payroll scan session cleared.", "info");
  }

  function exportCsv() {
    const headers = [
      "scanned_at",
      "employee_id",
      "employee_name",
      "department",
      "position",
      "production_no",
      "sales_order_no",
      "batch_no",
      "model",
      "operation_section",
      "operation_code",
      "operation_name",
      "quantity",
      "rate_per_piece",
      "total_pay",
      "currency",
    ];
    const rows = records.map((record) => [
      record.scannedAt,
      record.employeeId,
      record.employeeName,
      record.departmentName,
      record.position,
      record.productionNo,
      record.salesOrderNo,
      record.batchNo,
      record.modelCode,
      record.operationSection,
      record.operationCode,
      record.operationName,
      record.quantity,
      record.ratePerPiece,
      record.quantity * record.ratePerPiece,
      record.currency,
    ]);
    const csv = [headers, ...rows].map((row) => row.map(csvEscape).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `payroll-scans-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const messageClass = {
    info: "border-[#ded9ca] bg-[#f8f6ef] text-[#56503f]",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    error: "border-red-200 bg-red-50 text-red-700",
  }[messageTone];
  const latestVisibleRecord = visibleRecords[0] || null;

  return (
    <div>
      <PageHeader
        title="Payroll Scan"
        subtitle="Scan employee QR badges and work QR labels to calculate piecework pay."
        actions={(
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn" onClick={() => inputRef.current?.focus()}>
              <ScanLine />
              <span>Focus scanner</span>
            </button>
            <button type="button" className="btn" onClick={exportCsv} disabled={records.length === 0}>
              <Download />
              <span>CSV</span>
            </button>
            <button type="button" className="btn btn-danger" onClick={clearRecords} disabled={records.length === 0}>
              <Trash2 />
              <span>Clear</span>
            </button>
          </div>
        )}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(320px,440px)_minmax(0,1fr)]">
        <section className="card p-4">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="app-card-title">Scanner</h2>
              <p className="mt-1 text-xs text-[#8a8472]">Employee first, work second.</p>
            </div>
            <ScanLine className="h-5 w-5 text-[#8a8472]" />
          </div>

          <form onSubmit={submitScan} className="space-y-3">
            <div>
              <label className="label">QR input</label>
              <input
                ref={inputRef}
                className="input font-mono"
                autoFocus
                autoComplete="off"
                spellCheck={false}
                placeholder='{"type":"employee_payroll"...}'
                onChange={handleScanInput}
                onKeyDown={(event) => {
                  if (event.key === "Tab" && inputRef.current?.value.trim()) {
                    event.preventDefault();
                    submitScan();
                  }
                }}
              />
            </div>
            <button type="submit" className="btn btn-primary w-full" disabled={!inputHasText}>
              <ScanLine />
              <span>Scan</span>
            </button>
          </form>

          {message && (
            <div className={`mt-4 rounded-md border p-3 text-sm ${messageClass}`}>
              {message}
            </div>
          )}

          <div className="mt-4 rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
            <div className="mb-2 flex items-center gap-2">
              <UserCheck className="h-4 w-4 text-[#8a8472]" />
              <div className="label mb-0">Current employee</div>
            </div>
            {currentEmployee ? (
              <div>
                <div className="text-lg font-semibold">{currentEmployee.employee_name}</div>
                <div className="mt-1 text-sm text-[#56503f]">
                  EMP-{String(currentEmployee.employee_id).padStart(4, "0")}
                </div>
                <div className="mt-1 text-xs text-[#8a8472]">
                  {currentEmployee.department_name || "-"} - {currentEmployee.position || "-"}
                </div>
              </div>
            ) : (
              <div className="text-sm text-[#8a8472]">No employee selected.</div>
            )}
          </div>
        </section>

        <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="kpi-card">
            <div className="label">Employees</div>
            <div className="text-2xl font-semibold">{employeeSummaries.length.toLocaleString()}</div>
          </div>
          <div className="kpi-card">
            <div className="label">Pieces</div>
            <div className="text-2xl font-semibold">{totals.quantity.toLocaleString()}</div>
          </div>
          <div className="kpi-card">
            <div className="label">Paycheck total</div>
            <div className="text-2xl font-semibold">{formatMoney(totals.pay, totals.currency)}</div>
          </div>

          <div className="card p-4 lg:col-span-3">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="app-card-title">Paychecks</h2>
              <Calculator className="h-5 w-5 text-[#8a8472]" />
            </div>
            <div className="overflow-x-auto">
              <table className="table min-w-[760px]">
                <thead>
                  <tr>
                    <th>Employee</th>
                    <th>Department</th>
                    <th>Records</th>
                    <th>Pieces</th>
                    <th>Total pay</th>
                  </tr>
                </thead>
                <tbody>
                  {employeeSummaries.length === 0 && (
                    <tr>
                      <td colSpan={5} className="text-sm text-[#8a8472]">No payroll scans yet.</td>
                    </tr>
                  )}
                  {employeeSummaries.map((summary) => (
                    <tr key={summary.employeeId}>
                      <td>
                        <div className="font-medium">{summary.employeeName}</div>
                        <div className="text-xs text-[#8a8472]">EMP-{String(summary.employeeId).padStart(4, "0")}</div>
                      </td>
                      <td>{summary.departmentName}</td>
                      <td>{summary.records.length.toLocaleString()}</td>
                      <td>{summary.quantity.toLocaleString()}</td>
                      <td className="font-semibold">{formatMoney(summary.totalPay, summary.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
        <section className="card p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="app-card-title">Scan history</h2>
              <div className="mt-1 text-xs text-[#8a8472]">
                {currentEmployee ? `${currentEmployee.employee_name} only` : "No employee selected"}
                {currentEmployee && hiddenHistoryCount > 0 ? ` - showing latest ${visibleHistoryRows.length.toLocaleString()} of ${visibleRecords.length.toLocaleString()}` : ""}
              </div>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              {visibleRecords.length > HISTORY_RENDER_LIMIT && (
                <button
                  type="button"
                  className="btn"
                  onClick={() => setShowAllHistory((current) => !current)}
                >
                  <span>{showAllHistory ? "Show latest" : "Show all"}</span>
                </button>
              )}
              <button
                type="button"
                className="btn"
                onClick={() => {
                  if (latestVisibleRecord) removeRecord(latestVisibleRecord.id);
                }}
                disabled={!latestVisibleRecord}
              >
                <RefreshCw />
                <span>Undo last</span>
              </button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="table min-w-[1180px]">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Employee</th>
                  <th>Model</th>
                  <th>Production</th>
                  <th>Batch</th>
                  <th>Operation</th>
                  <th>Qty</th>
                  <th>Rate</th>
                  <th>Total</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {!currentEmployee && (
                  <tr>
                    <td colSpan={10} className="text-sm text-[#8a8472]">Scan an employee QR to view individual history.</td>
                  </tr>
                )}
                {currentEmployee && visibleRecords.length === 0 && (
                  <tr>
                    <td colSpan={10} className="text-sm text-[#8a8472]">No scans for {currentEmployee.employee_name} yet.</td>
                  </tr>
                )}
                {visibleHistoryRows.map((record) => (
                  <tr key={record.id}>
                    <td>{new Date(record.scannedAt).toLocaleString()}</td>
                    <td>{record.employeeName}</td>
                    <td>{record.modelCode}</td>
                    <td>{record.productionNo}</td>
                    <td>{record.batchNo}</td>
                    <td>
                      <div className="font-medium">{record.operationName}</div>
                      <div className="text-xs text-[#8a8472]">{record.operationSection} - {record.operationCode}</div>
                    </td>
                    <td>
                      <input
                        className="input w-24"
                        type="number"
                        min={0}
                        value={record.quantity}
                        onChange={(event) => updateRecord(record.id, { quantity: Number(event.target.value) })}
                      />
                    </td>
                    <td>
                      <input
                        className="input w-28"
                        type="number"
                        min={0}
                        step="0.01"
                        value={record.ratePerPiece}
                        onChange={(event) => updateRecord(record.id, { ratePerPiece: Number(event.target.value) })}
                      />
                    </td>
                    <td className="font-semibold">{formatMoney(record.quantity * record.ratePerPiece, record.currency)}</td>
                    <td>
                      <button type="button" className="icon-btn" onClick={() => removeRecord(record.id)} title="Remove scan">
                        <Trash2 />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card p-4">
          <div>
            <h2 className="app-card-title">By operation</h2>
            <div className="mt-1 text-xs text-[#8a8472]">
              {currentEmployee ? `${currentEmployee.employee_name} only` : "No employee selected"}
            </div>
          </div>
          <div className="mt-3 space-y-2">
            {operationSummaries.length === 0 && (
              <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3 text-sm text-[#8a8472]">
                {currentEmployee ? "No operation totals for this employee yet." : "Scan an employee QR to view operation totals."}
              </div>
            )}
            {operationSummaries.map((summary) => (
              <div key={summary.key} className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
                <div className="font-medium">{summary.label}</div>
                <div className="mt-1 flex justify-between text-sm text-[#56503f]">
                  <span>{summary.quantity.toLocaleString()} pcs</span>
                  <span className="font-semibold">{formatMoney(summary.totalPay, summary.currency)}</span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
