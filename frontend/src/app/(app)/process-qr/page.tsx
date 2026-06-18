"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import QRCode from "qrcode";
import {
  CheckSquare,
  Plus,
  Printer,
  QrCode,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Users,
} from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { formatBatchSerial } from "@/lib/batchSerial";
import { orderReference } from "@/lib/orderRef";
import {
  clonePaidOperations,
  createPaidOperation,
  paidOperationsFromDetails,
  SECTION_BADGES,
  SECTION_LABELS,
  serializePaidOperations,
  withPaidOperations,
  type PaidOperation,
  type SectionCode,
  type SplitMode,
} from "@/lib/modelPaidOperations";
import PageHeader from "@/components/PageHeader";

type Stage = {
  work_order_id: number;
  operation: string;
  status: string;
  planned: number;
  completed: number;
  failed: number;
  rework: number;
  progress_pct: number;
};

type ProcessBatch = {
  id: number;
  batch_no: string | null;
  batch_index: number;
  name: string | null;
  planned_quantity: number;
  current_stage: string;
  current_stage_status: string | null;
  stages: Stage[];
};

type Process = {
  production_order_id: number;
  production_no: string;
  order_no?: string | null;
  sales_order_id: number | null;
  sales_order_no: string | null;
  customer_name: string | null;
  model_id?: number | null;
  model_code: string | null;
  model_name: string | null;
  planned_quantity: number;
  current_stage: string;
  batches?: ProcessBatch[];
  stages: Stage[];
};

type Department = {
  id: number;
  name: string;
  code?: string | null;
};

type Employee = {
  id: number;
  user_id?: number | null;
  full_name: string;
  department_id: number | null;
  position: string | null;
  status: string;
  joined_at: string | null;
};

type BatchOption = {
  key: string;
  batchId: number | null;
  batchNo: string | null;
  batchIndex: number;
  name: string | null;
  plannedQuantity: number;
  currentStage: string;
  serial: string;
};

type LabelRow = {
  key: string;
  process: Process;
  batch: BatchOption;
  operation: PaidOperation;
  quantity: number;
  rate: number;
  currency: string;
  payload: string;
  copyIndex: number;
  copyCount: number;
  splitMode: SplitMode;
};

type EmployeeBadgeRow = {
  key: string;
  employee: Employee;
  departmentName: string;
  payload: string;
  copyIndex: number;
};

function numberOrZero(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function batchesForProcess(process: Process | undefined): BatchOption[] {
  if (!process) return [];
  const realBatches = Array.isArray(process.batches) ? process.batches : [];
  if (realBatches.length > 0) {
    return realBatches.map((batch) => ({
      key: `batch-${batch.id}`,
      batchId: batch.id,
      batchNo: batch.batch_no,
      batchIndex: Number(batch.batch_index || 1),
      name: batch.name,
      plannedQuantity: numberOrZero(batch.planned_quantity),
      currentStage: batch.current_stage,
      serial: formatBatchSerial(batch, process.production_order_id),
    }));
  }

  return [
    {
      key: `po-${process.production_order_id}`,
      batchId: null,
      batchNo: null,
      batchIndex: 1,
      name: "Whole order",
      plannedQuantity: numberOrZero(process.planned_quantity),
      currentStage: process.current_stage,
      serial: formatBatchSerial({ batch_index: 1 }, process.production_order_id),
    },
  ];
}

function batchDisplayName(batch: BatchOption): string {
  return batch.name ? `${batch.serial} - ${batch.name}` : batch.serial;
}

function money(value: number, currency: string): string {
  if (!value) return "-";
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`;
}

function compactQrValue(value: string | number | null | undefined, fallback = "-"): string {
  if (value === null || value === undefined || value === "") return fallback;
  const text = String(value)
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^0-9A-Z $%+\-./:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text || fallback;
}

function compactQrNumber(value: string | number | null | undefined, fallback = "-"): string {
  if (value === null || value === undefined || value === "") return fallback;
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return String(n);
}

function compactWorkPayload(
  process: Process,
  batch: BatchOption,
  operation: PaidOperation,
  quantity: number,
  rate: number,
  currency: string,
  copyIndex: number,
): string {
  return [
    "MW2",
    compactQrNumber(process.production_order_id),
    compactQrValue(process.production_no),
    compactQrNumber(batch.batchId),
    compactQrValue(batch.batchNo || batch.serial),
    compactQrNumber(batch.batchIndex),
    compactQrValue(process.model_code || process.model_id),
    compactQrValue(operation.section),
    compactQrValue(operation.code),
    compactQrValue(operation.name),
    compactQrNumber(quantity),
    compactQrNumber(rate),
    compactQrValue(currency || "UZS"),
    compactQrNumber(copyIndex),
  ].join("*");
}

function compactEmployeePayload(employee: Employee, departmentName: string, copyIndex: number): string {
  return [
    "ME2",
    compactQrNumber(employee.id),
    compactQrNumber(employee.user_id),
    compactQrValue(employee.full_name || `Employee ${employee.id}`),
    compactQrNumber(employee.department_id),
    compactQrValue(departmentName),
    compactQrValue(employee.position),
    compactQrValue(employee.status || "active"),
    compactQrNumber(copyIndex),
  ].join("*");
}

function roundedPieces(value: number): number {
  return Math.max(0, Math.round((value + Number.EPSILON) * 100) / 100);
}

function equalSplitQuantities(totalQuantity: number, copies: number): number[] {
  const safeCopies = Math.max(1, Math.floor(numberOrZero(copies) || 1));
  const total = Math.max(0, numberOrZero(totalQuantity));
  if (safeCopies === 1) return [roundedPieces(total)];

  if (Number.isInteger(total)) {
    const base = Math.floor(total / safeCopies);
    const remainder = Math.round(total - base * safeCopies);
    return Array.from({ length: safeCopies }, (_, index) => base + (index < remainder ? 1 : 0));
  }

  const share = roundedPieces(total / safeCopies);
  return Array.from({ length: safeCopies }, (_, index) => (
    index === safeCopies - 1
      ? roundedPieces(total - share * (safeCopies - 1))
      : share
  ));
}

function quantitiesForOperationLabels(operation: PaidOperation, totalQuantity: number, copies: number): number[] {
  const safeCopies = Math.max(1, Math.floor(numberOrZero(copies) || 1));
  const total = Math.max(0, numberOrZero(totalQuantity));
  if (operation.splitMode === "equal") return equalSplitQuantities(total, safeCopies);
  if (operation.splitMode === "custom") {
    return Array.from({ length: safeCopies }, (_, index) => (
      Math.max(0, numberOrZero(operation.splitQuantities?.[index]))
    ));
  }
  return Array.from({ length: safeCopies }, () => total);
}

function splitQuantitiesForInputs(operation: PaidOperation): number[] {
  const copies = Math.max(1, Math.floor(numberOrZero(operation.copies) || 1));
  return Array.from({ length: copies }, (_, index) => Math.max(0, numberOrZero(operation.splitQuantities?.[index])));
}

export default function ProcessQrPage() {
  const { data = [], error, isLoading, mutate } = useSWR<Process[]>(
    "/api/process-tracking",
    fetcher,
    { refreshInterval: 15_000 },
  );
  const { data: employees = [], error: employeesError, isLoading: employeesLoading, mutate: mutateEmployees } = useSWR<Employee[]>(
    "/api/employees",
    fetcher,
  );
  const { data: departments = [] } = useSWR<Department[]>("/api/departments", fetcher);
  const [query, setQuery] = useState("");
  const [selectedProcessId, setSelectedProcessId] = useState<number | null>(null);
  const [batchMode, setBatchMode] = useState<"selected" | "all">("selected");
  const [selectedBatchKey, setSelectedBatchKey] = useState("");
  const [currency, setCurrency] = useState("UZS");
  const [operations, setOperations] = useState<PaidOperation[]>(() => clonePaidOperations());
  const [loadedOperationsModelId, setLoadedOperationsModelId] = useState<number | null>(null);
  const [loadedOperationsSignature, setLoadedOperationsSignature] = useState("");
  const [operationModelDirty, setOperationModelDirty] = useState(false);
  const [savingModelOperations, setSavingModelOperations] = useState(false);
  const [modelSaveMsg, setModelSaveMsg] = useState("");
  const [employeeQuery, setEmployeeQuery] = useState("");
  const [employeeStatus, setEmployeeStatus] = useState<"active" | "all">("active");
  const [employeeCopies, setEmployeeCopies] = useState(1);
  const [selectedEmployeeIds, setSelectedEmployeeIds] = useState<number[]>([]);
  const [employeeSelectionInitialized, setEmployeeSelectionInitialized] = useState(false);
  const [printMode, setPrintMode] = useState<"work" | "employees">("work");

  const filteredProcesses = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return data;
    return data.filter((process) => {
      const haystack = [
        process.order_no,
        process.production_no,
        process.sales_order_no,
        process.customer_name,
        process.model_code,
        process.model_name,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [data, query]);

  const selectedProcess = useMemo(() => {
    if (selectedProcessId == null) return filteredProcesses[0] || data[0];
    return (
      filteredProcesses.find((process) => process.production_order_id === selectedProcessId)
      || filteredProcesses[0]
      || data.find((process) => process.production_order_id === selectedProcessId)
      || data[0]
    );
  }, [data, filteredProcesses, selectedProcessId]);

  const selectedModelId = selectedProcess?.model_id ? Number(selectedProcess.model_id) : null;
  const { data: selectedModel, mutate: mutateSelectedModel } = useSWR<any>(
    selectedModelId ? `/api/models/${selectedModelId}` : null,
    fetcher,
  );
  const batchOptions = useMemo(() => batchesForProcess(selectedProcess), [selectedProcess]);
  const departmentById = useMemo(
    () => new Map(departments.map((department) => [Number(department.id), department])),
    [departments],
  );

  const filteredEmployees = useMemo(() => {
    const q = employeeQuery.trim().toLowerCase();
    return employees
      .filter((employee) => employeeStatus === "all" || String(employee.status || "").toLowerCase() === "active")
      .filter((employee) => {
        if (!q) return true;
        const department = employee.department_id ? departmentById.get(Number(employee.department_id)) : null;
        const haystack = [
          employee.full_name,
          employee.position,
          employee.status,
          department?.name,
          department?.code,
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        return haystack.includes(q);
      })
      .sort((a, b) => a.full_name.localeCompare(b.full_name));
  }, [departmentById, employeeQuery, employeeStatus, employees]);

  useEffect(() => {
    if (
      filteredProcesses.length > 0
      && (selectedProcessId == null || !filteredProcesses.some((process) => process.production_order_id === selectedProcessId))
    ) {
      setSelectedProcessId(filteredProcesses[0].production_order_id);
    }
  }, [filteredProcesses, selectedProcessId]);

  useEffect(() => {
    if (!batchOptions.length) {
      setSelectedBatchKey("");
      return;
    }
    if (!batchOptions.some((batch) => batch.key === selectedBatchKey)) {
      setSelectedBatchKey(batchOptions[0].key);
    }
  }, [batchOptions, selectedBatchKey]);

  useEffect(() => {
    if (!selectedModelId) {
      if (loadedOperationsModelId !== null) {
        setOperations(clonePaidOperations());
        setLoadedOperationsModelId(null);
        setLoadedOperationsSignature("");
        setOperationModelDirty(false);
        setModelSaveMsg("");
      }
      return;
    }
    if (!selectedModel) return;

    const nextOperations = paidOperationsFromDetails(selectedModel.details_json);
    const nextSignature = JSON.stringify(serializePaidOperations(nextOperations));
    const sameModel = loadedOperationsModelId === selectedModelId;
    if (sameModel && operationModelDirty) return;
    if (sameModel && loadedOperationsSignature === nextSignature) return;

    setOperations(nextOperations);
    setLoadedOperationsModelId(selectedModelId);
    setLoadedOperationsSignature(nextSignature);
    setOperationModelDirty(false);
    setModelSaveMsg(`Loaded model operations from ${selectedModel.code || selectedProcess?.model_code || "model"}.`);
  }, [
    loadedOperationsModelId,
    loadedOperationsSignature,
    operationModelDirty,
    selectedModel,
    selectedModelId,
    selectedProcess?.model_code,
  ]);

  useEffect(() => {
    if (employeeSelectionInitialized || employees.length === 0) return;
    setSelectedEmployeeIds(
      employees
        .filter((employee) => String(employee.status || "").toLowerCase() === "active")
        .map((employee) => Number(employee.id)),
    );
    setEmployeeSelectionInitialized(true);
  }, [employeeSelectionInitialized, employees]);

  useEffect(() => {
    const resetPrintMode = () => setPrintMode("work");
    window.addEventListener("afterprint", resetPrintMode);
    return () => window.removeEventListener("afterprint", resetPrintMode);
  }, []);

  const batchesToPrint = useMemo(() => {
    if (batchMode === "all") return batchOptions;
    return batchOptions.filter((batch) => batch.key === selectedBatchKey);
  }, [batchMode, batchOptions, selectedBatchKey]);

  const selectedOperations = useMemo(
    () => operations.filter((operation) => operation.selected && operation.code.trim() && operation.name.trim()),
    [operations],
  );

  const labels = useMemo<LabelRow[]>(() => {
    if (!selectedProcess) return [];
    const rows: LabelRow[] = [];
    for (const batch of batchesToPrint) {
      for (const operation of selectedOperations) {
        const baseQuantity = operation.quantityMode === "custom"
          ? Math.max(0, numberOrZero(operation.customQuantity))
          : Math.max(0, numberOrZero(batch.plannedQuantity));
        const copies = Math.max(1, Math.floor(numberOrZero(operation.copies) || 1));
        const rate = Math.max(0, numberOrZero(operation.rate));
        const labelQuantities = quantitiesForOperationLabels(operation, baseQuantity, copies);
        for (let copyIndex = 1; copyIndex <= copies; copyIndex += 1) {
          const quantity = labelQuantities[copyIndex - 1] ?? 0;
          const payload = compactWorkPayload(selectedProcess, batch, operation, quantity, rate, currency, copyIndex);

          rows.push({
            key: `${batch.key}-${operation.id}-${copyIndex}`,
            process: selectedProcess,
            batch,
            operation,
            quantity,
            rate,
            currency,
            payload,
            copyIndex,
            copyCount: copies,
            splitMode: operation.splitMode,
          });
        }
      }
    }
    return rows;
  }, [batchesToPrint, currency, selectedOperations, selectedProcess]);

  const selectedEmployeeIdSet = useMemo(() => new Set(selectedEmployeeIds), [selectedEmployeeIds]);

  const employeeBadgeRows = useMemo<EmployeeBadgeRow[]>(() => {
    const rows: EmployeeBadgeRow[] = [];
    const copies = Math.max(1, Math.floor(numberOrZero(employeeCopies) || 1));
    for (const employee of filteredEmployees) {
      if (!selectedEmployeeIdSet.has(Number(employee.id))) continue;
      const department = employee.department_id ? departmentById.get(Number(employee.department_id)) : null;
      const departmentName = department ? `${department.code ? `${department.code} - ` : ""}${department.name}` : "-";
      for (let copyIndex = 1; copyIndex <= copies; copyIndex += 1) {
        rows.push({
          key: `employee-${employee.id}-${copyIndex}`,
          employee,
          departmentName,
          copyIndex,
          payload: compactEmployeePayload(employee, departmentName, copyIndex),
        });
      }
    }
    return rows;
  }, [departmentById, employeeCopies, filteredEmployees, selectedEmployeeIdSet]);

  function markOperationsDirty() {
    setOperationModelDirty(true);
    setModelSaveMsg("");
  }

  function updateOperation(id: string, patch: Partial<PaidOperation>) {
    markOperationsDirty();
    setOperations((current) => current.map((operation) => (
      operation.id === id ? { ...operation, ...patch } : operation
    )));
  }

  function addOperation() {
    markOperationsDirty();
    setOperations((current) => [
      ...current,
      createPaidOperation("op", selectedProcess?.planned_quantity || 0),
    ]);
  }

  function removeOperation(id: string) {
    markOperationsDirty();
    setOperations((current) => current.filter((operation) => operation.id !== id));
  }

  function loadOperationsFromSelectedModel() {
    if (!selectedModel || !selectedModelId) return;
    const nextOperations = paidOperationsFromDetails(selectedModel.details_json);
    const nextSignature = JSON.stringify(serializePaidOperations(nextOperations));
    setOperations(nextOperations);
    setLoadedOperationsModelId(selectedModelId);
    setLoadedOperationsSignature(nextSignature);
    setOperationModelDirty(false);
    setModelSaveMsg(`Loaded model operations from ${selectedModel.code || selectedProcess?.model_code || "model"}.`);
  }

  async function saveOperationsToModel() {
    if (!selectedModel || !selectedModelId) return;
    setSavingModelOperations(true);
    setModelSaveMsg("");
    try {
      const nextOperations = serializePaidOperations(operations);
      const nextDetails = withPaidOperations(selectedModel.details_json, nextOperations);
      await api.patch(`/api/models/${selectedModelId}`, {
        code: selectedModel.code,
        name: selectedModel.name,
        category: selectedModel.category || null,
        description: selectedModel.description || null,
        brand_id: selectedModel.brand_id || null,
        collection_id: selectedModel.collection_id || null,
        product_type: selectedModel.product_type || null,
        season: selectedModel.season || null,
        constructor_employee_id: selectedModel.constructor_employee_id || null,
        designer_employee_id: selectedModel.designer_employee_id || null,
        details_json: nextDetails,
        status: selectedModel.status || "draft",
        sam_minutes: numberOrZero(selectedModel.sam_minutes),
      });
      await mutateSelectedModel();
      setOperations(nextOperations);
      setLoadedOperationsModelId(selectedModelId);
      setLoadedOperationsSignature(JSON.stringify(nextOperations));
      setOperationModelDirty(false);
      setModelSaveMsg(`Saved to model ${selectedModel.code || selectedProcess?.model_code || ""}.`);
    } catch (err: any) {
      setModelSaveMsg(err?.message ? `Could not save model operations: ${err.message}` : "Could not save model operations.");
    } finally {
      setSavingModelOperations(false);
    }
  }

  function printLabels() {
    setPrintMode("work");
    window.setTimeout(() => window.print(), 80);
  }

  function printEmployeeBadges() {
    setPrintMode("employees");
    window.setTimeout(() => window.print(), 80);
  }

  function toggleEmployee(employeeId: number, checked: boolean) {
    setSelectedEmployeeIds((current) => (
      checked
        ? Array.from(new Set([...current, employeeId]))
        : current.filter((id) => id !== employeeId)
    ));
  }

  function selectVisibleEmployees() {
    setSelectedEmployeeIds((current) => Array.from(new Set([
      ...current,
      ...filteredEmployees.map((employee) => Number(employee.id)),
    ])));
  }

  function clearVisibleEmployees() {
    const visibleIds = new Set(filteredEmployees.map((employee) => Number(employee.id)));
    setSelectedEmployeeIds((current) => current.filter((id) => !visibleIds.has(id)));
  }

  const totalPieces = labels.reduce((sum, label) => sum + label.quantity, 0);
  const totalEstimatedPay = labels.reduce((sum, label) => sum + label.quantity * label.rate, 0);

  return (
    <div className={`process-qr-page print-mode-${printMode}`}>
      <div className="no-print">
        <PageHeader
          title="Process QR Labels"
          subtitle="Generate employee badges and paid-operation labels for payroll scanning."
          actions={(
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn" onClick={() => { mutate(); mutateEmployees(); }} title="Refresh data">
                <RefreshCw />
                <span>Refresh</span>
              </button>
              <button type="button" className="btn" onClick={printEmployeeBadges} disabled={employeeBadgeRows.length === 0}>
                <Users />
                <span>Print employees</span>
              </button>
              <button type="button" className="btn btn-primary" onClick={printLabels} disabled={labels.length === 0}>
                <Printer />
                <span>Print labels</span>
              </button>
            </div>
          )}
        />
      </div>

      {error && (
        <div className="card mb-4 border-red-200 bg-red-50 p-3 text-sm text-red-700 no-print">
          {String((error as Error).message || error)}
        </div>
      )}
      {employeesError && (
        <div className="card mb-4 border-red-200 bg-red-50 p-3 text-sm text-red-700 no-print">
          {String((employeesError as Error).message || employeesError)}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(320px,430px)_minmax(0,1fr)] no-print">
        <section className="card p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="app-card-title">Batch source</h2>
              <p className="mt-1 text-xs text-[#8a8472]">Choose the order and batch that will receive these labels.</p>
            </div>
            <QrCode className="h-5 w-5 text-[#8a8472]" />
          </div>

          <label className="label">Search order</label>
          <div className="mb-3 flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 shadow-sm">
            <Search className="h-4 w-4 text-[#8a8472]" />
            <input
              className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
              placeholder="Order, customer, model..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>

          <label className="label">Order</label>
          <select
            className="input mb-3"
            value={selectedProcess?.production_order_id || ""}
            onChange={(event) => setSelectedProcessId(Number(event.target.value))}
            disabled={isLoading || filteredProcesses.length === 0}
          >
            {filteredProcesses.map((process) => (
              <option key={process.production_order_id} value={process.production_order_id}>
                {orderReference(process, process.production_no)} - {process.model_code || "No model"}{process.customer_name ? ` - ${process.customer_name}` : ""}
              </option>
            ))}
          </select>

          <div className="mb-3 grid grid-cols-2 gap-2">
            <button
              type="button"
              className={`btn ${batchMode === "selected" ? "btn-primary" : ""}`}
              onClick={() => setBatchMode("selected")}
            >
              One batch
            </button>
            <button
              type="button"
              className={`btn ${batchMode === "all" ? "btn-primary" : ""}`}
              onClick={() => setBatchMode("all")}
            >
              All batches
            </button>
          </div>

          {batchMode === "selected" && (
            <>
              <label className="label">Batch</label>
              <select
                className="input mb-3"
                value={selectedBatchKey}
                onChange={(event) => setSelectedBatchKey(event.target.value)}
                disabled={batchOptions.length === 0}
              >
                {batchOptions.map((batch) => (
                  <option key={batch.key} value={batch.key}>
                    {batchDisplayName(batch)} - {batch.plannedQuantity.toLocaleString()} pcs
                  </option>
                ))}
              </select>
            </>
          )}

          <label className="label">Currency for rates</label>
          <input
            className="input mb-4"
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
            maxLength={8}
          />

          {selectedProcess ? (
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3 text-sm">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="font-medium">{orderReference(selectedProcess, selectedProcess.production_no)}</span>
                <Link className="text-xs text-[#c2410c] hover:underline" href={`/production-orders/${selectedProcess.production_order_id}`}>
                  Open order
                </Link>
              </div>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <dt className="text-[#8a8472]">Model</dt>
                <dd>{selectedProcess.model_code || "-"}</dd>
                <dt className="text-[#8a8472]">Customer</dt>
                <dd>{selectedProcess.customer_name || "-"}</dd>
                <dt className="text-[#8a8472]">Order qty</dt>
                <dd>{numberOrZero(selectedProcess.planned_quantity).toLocaleString()} pcs</dd>
                <dt className="text-[#8a8472]">Batches</dt>
                <dd>{batchOptions.length.toLocaleString()}</dd>
              </dl>
            </div>
          ) : (
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3 text-sm text-[#8a8472]">
              {isLoading ? "Loading production batches..." : "No active production orders found."}
            </div>
          )}
        </section>

        <section className="card p-4">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="app-card-title">Paid operations</h2>
              <p className="mt-1 text-xs text-[#8a8472]">Each selected row becomes a QR label per chosen batch.</p>
              {modelSaveMsg && (
                <p className={`mt-1 text-xs ${modelSaveMsg.startsWith("Could not") ? "text-red-700" : "text-green-700"}`}>
                  {modelSaveMsg}
                </p>
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="btn"
                onClick={loadOperationsFromSelectedModel}
                disabled={!selectedModelId || !selectedModel}
                title="Load saved operations from selected model"
              >
                <RefreshCw />
                <span>Load model</span>
              </button>
              <button
                type="button"
                className="btn"
                onClick={saveOperationsToModel}
                disabled={!selectedModelId || !selectedModel || savingModelOperations}
                title="Save these operations to selected model"
              >
                <Save />
                <span>{savingModelOperations ? "Saving..." : "Save to model"}</span>
              </button>
              <button type="button" className="btn" onClick={addOperation}>
                <Plus />
                <span>Add operation</span>
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="table min-w-[1180px]">
              <thead>
                <tr>
                  <th className="w-12">Use</th>
                  <th>Section</th>
                  <th>Code</th>
                  <th>Operation name</th>
                  <th>Qty</th>
                  <th>Rate / pc</th>
                  <th>Copies</th>
                  <th>Divide</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {operations.map((operation) => {
                  const splitInputs = splitQuantitiesForInputs(operation);
                  return (
                  <tr key={operation.id}>
                    <td>
                      <input
                        type="checkbox"
                        className="h-4 w-4"
                        checked={operation.selected}
                        onChange={(event) => updateOperation(operation.id, { selected: event.target.checked })}
                      />
                    </td>
                    <td>
                      <select
                        className="input min-w-[130px]"
                        value={operation.section}
                        onChange={(event) => updateOperation(operation.id, { section: event.target.value as SectionCode })}
                      >
                        <option value="sewing">Sewing</option>
                        <option value="pressing">Pressing</option>
                        <option value="packaging">Packaging</option>
                      </select>
                    </td>
                    <td>
                      <input
                        className="input min-w-[120px] font-mono"
                        value={operation.code}
                        onChange={(event) => updateOperation(operation.id, { code: event.target.value.toUpperCase() })}
                      />
                    </td>
                    <td>
                      <input
                        className="input min-w-[190px]"
                        value={operation.name}
                        onChange={(event) => updateOperation(operation.id, { name: event.target.value })}
                      />
                    </td>
                    <td>
                      <div className="flex min-w-[190px] gap-2">
                        <select
                          className="input w-[92px]"
                          value={operation.quantityMode}
                          onChange={(event) => updateOperation(operation.id, { quantityMode: event.target.value as "batch" | "custom" })}
                        >
                          <option value="batch">Batch</option>
                          <option value="custom">Custom</option>
                        </select>
                        <input
                          className="input"
                          type="number"
                          min={0}
                          value={operation.customQuantity}
                          disabled={operation.quantityMode === "batch"}
                          onChange={(event) => updateOperation(operation.id, { customQuantity: Number(event.target.value) })}
                        />
                      </div>
                    </td>
                    <td>
                      <input
                        className="input min-w-[110px]"
                        type="number"
                        min={0}
                        step="0.01"
                        placeholder="0"
                        value={operation.rate}
                        onChange={(event) => updateOperation(operation.id, { rate: event.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        className="input w-20"
                        type="number"
                        min={1}
                        value={operation.copies}
                        onChange={(event) => updateOperation(operation.id, { copies: Number(event.target.value) })}
                      />
                    </td>
                    <td>
                      <div className="min-w-[260px] space-y-2">
                        <select
                          className="input"
                          value={operation.splitMode}
                          onChange={(event) => updateOperation(operation.id, { splitMode: event.target.value as SplitMode })}
                        >
                          <option value="none">No divide</option>
                          <option value="equal">Equal divide</option>
                          <option value="custom">Custom divide</option>
                        </select>
                        {operation.splitMode === "equal" && (
                          <div className="text-xs text-[#8a8472]">
                            Each copy gets an equal share of the qty.
                          </div>
                        )}
                        {operation.splitMode === "custom" && (
                          <div className="grid grid-cols-2 gap-2">
                            {splitInputs.map((quantity, index) => (
                              <label key={`${operation.id}-split-${index}`} className="flex items-center gap-1 text-[11px] text-[#6b6251]">
                                <span className="w-7 shrink-0">#{index + 1}</span>
                                <input
                                  className="input h-9 min-w-0"
                                  type="number"
                                  min={0}
                                  value={quantity}
                                  onChange={(event) => {
                                    const nextQuantities = splitQuantitiesForInputs(operation);
                                    nextQuantities[index] = Number(event.target.value);
                                    updateOperation(operation.id, { splitQuantities: nextQuantities });
                                  }}
                                />
                              </label>
                            ))}
                          </div>
                        )}
                      </div>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="icon-btn"
                        title="Remove operation"
                        onClick={() => removeOperation(operation.id)}
                        disabled={operations.length <= 1}
                      >
                        <Trash2 />
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
              <div className="label">Labels</div>
              <div className="text-2xl font-semibold">{labels.length.toLocaleString()}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
              <div className="label">Counted pieces</div>
              <div className="text-2xl font-semibold">{totalPieces.toLocaleString()}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
              <div className="label">Estimated pay</div>
              <div className="text-2xl font-semibold">{money(totalEstimatedPay, currency)}</div>
            </div>
          </div>
        </section>
      </div>

      <section className="mt-4 card p-4 no-print">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="app-card-title">Employee QR badges</h2>
            <p className="mt-1 text-xs text-[#8a8472]">Scan one employee badge first, then scan that employee work labels.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn" onClick={selectVisibleEmployees}>
              Select visible
            </button>
            <button type="button" className="btn" onClick={clearVisibleEmployees}>
              Clear visible
            </button>
            <button type="button" className="btn btn-primary" onClick={printEmployeeBadges} disabled={employeeBadgeRows.length === 0}>
              <Printer />
              <span>Print employees</span>
            </button>
          </div>
        </div>

        <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(260px,1fr)_180px_140px]">
          <div>
            <label className="label">Search employee</label>
            <div className="flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 shadow-sm">
              <Search className="h-4 w-4 text-[#8a8472]" />
              <input
                className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
                placeholder="Name, department, position..."
                value={employeeQuery}
                onChange={(event) => setEmployeeQuery(event.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label">Employees</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                className={`btn ${employeeStatus === "active" ? "btn-primary" : ""}`}
                onClick={() => setEmployeeStatus("active")}
              >
                Active
              </button>
              <button
                type="button"
                className={`btn ${employeeStatus === "all" ? "btn-primary" : ""}`}
                onClick={() => setEmployeeStatus("all")}
              >
                All
              </button>
            </div>
          </div>
          <div>
            <label className="label">Copies</label>
            <input
              className="input"
              type="number"
              min={1}
              value={employeeCopies}
              onChange={(event) => setEmployeeCopies(Number(event.target.value))}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
          <div className="overflow-x-auto">
            <table className="table min-w-[760px]">
              <thead>
                <tr>
                  <th className="w-12">Use</th>
                  <th>Employee</th>
                  <th>Department</th>
                  <th>Position</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {employeesLoading && (
                  <tr>
                    <td colSpan={5} className="text-sm text-[#8a8472]">Loading employees...</td>
                  </tr>
                )}
                {!employeesLoading && filteredEmployees.length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-sm text-[#8a8472]">No employees found.</td>
                  </tr>
                )}
                {filteredEmployees.map((employee) => {
                  const department = employee.department_id ? departmentById.get(Number(employee.department_id)) : null;
                  return (
                    <tr key={employee.id}>
                      <td>
                        <input
                          type="checkbox"
                          className="h-4 w-4"
                          checked={selectedEmployeeIdSet.has(Number(employee.id))}
                          onChange={(event) => toggleEmployee(Number(employee.id), event.target.checked)}
                        />
                      </td>
                      <td>
                        <div className="font-medium">{employee.full_name}</div>
                        <div className="text-xs text-[#8a8472]">EMP-{String(employee.id).padStart(4, "0")}</div>
                      </td>
                      <td>{department ? `${department.code ? `${department.code} - ` : ""}${department.name}` : "-"}</td>
                      <td>{employee.position || "-"}</td>
                      <td>
                        <span className={`badge ${employee.status === "active" ? "badge-green" : "badge-red"}`}>
                          {employee.status.replaceAll("_", " ")}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
            <div className="mb-3 grid grid-cols-2 gap-3">
              <div>
                <div className="label">Selected</div>
                <div className="text-2xl font-semibold">{employeeBadgeRows.length.toLocaleString()}</div>
              </div>
              <div>
                <div className="label">Visible</div>
                <div className="text-2xl font-semibold">{filteredEmployees.length.toLocaleString()}</div>
              </div>
            </div>
            <div className="text-xs text-[#8a8472]">
              Employee QR carries the employee ID, name, department, position, and status for payroll scanning.
            </div>
          </div>
        </div>
      </section>

      <section className="mt-5 print-sheet employee-print-section">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 no-print">
          <div>
            <h2 className="app-card-title">Employee badge preview</h2>
            <p className="mt-1 text-xs text-[#8a8472]">Print these badges for payroll identity scans.</p>
          </div>
          <div className="inline-flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 text-xs text-[#56503f]">
            <Users className="h-4 w-4" />
            {employeeBadgeRows.length.toLocaleString()} employee badge{employeeBadgeRows.length === 1 ? "" : "s"}
          </div>
        </div>

        {employeeBadgeRows.length > 0 ? (
          <div className="label-grid">
            {employeeBadgeRows.map((row) => (
              <EmployeeBadge key={row.key} row={row} />
            ))}
          </div>
        ) : (
          <div className="card p-6 text-sm text-[#8a8472] no-print">
            Select at least one employee to generate employee QR badges.
          </div>
        )}
      </section>

      <section className="mt-5 print-sheet work-print-section">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 no-print">
          <div>
            <h2 className="app-card-title">Label preview</h2>
            <p className="mt-1 text-xs text-[#8a8472]">
              Work QR carries the batch, operation, quantity, rate, and currency for payroll scanning.
            </p>
          </div>
          <div className="inline-flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 text-xs text-[#56503f]">
            <CheckSquare className="h-4 w-4" />
            {batchesToPrint.length.toLocaleString()} batch group{batchesToPrint.length === 1 ? "" : "s"} selected
          </div>
        </div>

        {labels.length > 0 ? (
          <div className="label-grid">
            {labels.map((label) => (
              <ProcessLabel key={label.key} label={label} />
            ))}
          </div>
        ) : (
          <div className="card p-6 text-sm text-[#8a8472] no-print">
            Select a production order, batch, and at least one paid operation to generate QR labels.
          </div>
        )}
      </section>

      <style jsx global>{`
        .label-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
          gap: 12px;
        }

        .process-label {
          min-height: 168px;
          overflow: hidden;
          border: 1px solid #d8d2c2;
          border-radius: 8px;
          background: #fff;
          color: #111;
          box-shadow: 0 1px 2px rgba(20, 17, 11, 0.07);
        }

        .process-label__qr {
          display: block;
          height: 112px;
          width: 112px;
          flex: 0 0 112px;
          object-fit: contain;
          background: #fff;
          image-rendering: pixelated;
        }

        @media print {
          @page {
            size: A4;
            margin: 8mm;
          }

          body {
            background: #fff !important;
          }

          aside,
          header,
          .no-print {
            display: none !important;
          }

          main {
            padding: 0 !important;
          }

          .process-qr-page.print-mode-work .employee-print-section,
          .process-qr-page.print-mode-employees .work-print-section {
            display: none !important;
          }

          .print-sheet {
            margin: 0 !important;
          }

          .label-grid {
            display: block;
            font-size: 0;
          }

          .process-label {
            display: inline-flex;
            vertical-align: top;
            width: 62mm;
            height: 40mm;
            min-height: 40mm;
            margin: 0 3mm 3mm 0;
            break-inside: avoid;
            page-break-inside: avoid;
            break-before: auto;
            break-after: auto;
            border: 0.35mm solid #d8d2c2;
            border-radius: 2.5mm;
            box-shadow: none !important;
            font-size: 10px;
          }

          .process-label__qr {
            height: 26mm;
            width: 26mm;
            flex-basis: 26mm;
          }
        }
      `}</style>
    </div>
  );
}

function EmployeeBadge({ row }: { row: EmployeeBadgeRow }) {
  const { employee, departmentName, payload } = row;
  return (
    <article className="process-label flex flex-col p-3">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[10px] font-bold uppercase tracking-[0.12em] text-[#6b6251]">
            Milana employee
          </div>
          <div className="truncate text-[13px] font-bold leading-tight text-[#111]">
            {employee.full_name}
          </div>
        </div>
        <span className={`badge shrink-0 ${employee.status === "active" ? "badge-green" : "badge-red"}`}>
          {employee.status.replaceAll("_", " ")}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 gap-2">
        <div className="min-w-0 flex-1 text-[10px] leading-tight">
          <LabelLine label="ID" value={`EMP-${String(employee.id).padStart(4, "0")}`} strong />
          <LabelLine label="Dept" value={departmentName} />
          <LabelLine label="Role" value={employee.position || "-"} />
          <LabelLine label="Scan" value="Employee first" strong />
        </div>
        <ProcessQrImage payload={payload} alt="Employee payroll QR" />
      </div>

      <div className="mt-1 flex items-center justify-between gap-2 border-t border-[#e8e3d6] pt-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[#6b6251]">
        <span className="truncate">EMPLOYEE_PAYROLL</span>
        <span className="shrink-0">EMP-{String(employee.id).padStart(4, "0")}</span>
      </div>
    </article>
  );
}

function ProcessLabel({ label }: { label: LabelRow }) {
  const { process, batch, operation, quantity, rate, currency, payload, copyIndex, copyCount, splitMode } = label;
  const amount = quantity * rate;

  return (
    <article className="process-label flex flex-col p-3">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[10px] font-bold uppercase tracking-[0.12em] text-[#6b6251]">
            Milana process
          </div>
          <div className="truncate text-[13px] font-bold leading-tight text-[#111]">
            {operation.name}
          </div>
        </div>
        <span className={`badge shrink-0 ${SECTION_BADGES[operation.section]}`}>
          {SECTION_LABELS[operation.section]}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 gap-2">
        <div className="min-w-0 flex-1 text-[10px] leading-tight">
          <LabelLine label="Model" value={process.model_code || "-"} />
          <LabelLine label="Order" value={orderReference(process, process.production_no)} />
          <LabelLine label="Batch" value={batchDisplayName(batch)} />
          <LabelLine label="Qty" value={`${quantity.toLocaleString()} pcs`} strong />
          {splitMode !== "none" && <LabelLine label="Part" value={`${copyIndex}/${copyCount}`} strong />}
          <LabelLine label="Rate" value={rate ? `${rate.toLocaleString()} ${currency}` : "-"} />
          <LabelLine label="Total" value={amount ? `${amount.toLocaleString()} ${currency}` : "-"} />
        </div>
        <ProcessQrImage payload={payload} alt="Process payroll QR" />
      </div>

      <div className="mt-1 flex items-center justify-between gap-2 border-t border-[#e8e3d6] pt-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[#6b6251]">
        <span className="truncate">{operation.code}</span>
        <span className="shrink-0">{batch.serial}</span>
      </div>
    </article>
  );
}

function LabelLine({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="grid grid-cols-[33px_minmax(0,1fr)] gap-1">
      <span className="text-[#7a725f]">{label}</span>
      <span className={`truncate ${strong ? "font-bold" : "font-medium"}`}>{value}</span>
    </div>
  );
}

function ProcessQrImage({ payload, alt = "Payroll QR" }: { payload: string; alt?: string }) {
  const [src, setSrc] = useState("");

  useEffect(() => {
    let active = true;
    QRCode.toDataURL(payload, {
      errorCorrectionLevel: "L",
      margin: 1,
      width: 240,
      color: {
        dark: "#111111",
        light: "#ffffff",
      },
    })
      .then((url) => {
        if (active) setSrc(url);
      })
      .catch(() => {
        if (active) setSrc("");
      });

    return () => {
      active = false;
    };
  }, [payload]);

  if (!src) {
    return (
      <div className="process-label__qr flex items-center justify-center rounded border border-[#d8d2c2] text-[10px] font-semibold text-[#8a8472]">
        QR
      </div>
    );
  }

  return <img className="process-label__qr" src={src} alt={alt} />;
}
