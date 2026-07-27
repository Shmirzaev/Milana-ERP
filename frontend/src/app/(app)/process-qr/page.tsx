"use client";

import { useEffect, useMemo, useRef, useState } from "react";
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
import { parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import {
  clonePaidOperations,
  createPaidOperation,
  paidOperationsFromDetails,
  SECTION_BADGES,
  serializePaidOperations,
  withPaidOperations,
  type PaidOperation,
  type SectionCode,
  type SplitMode,
} from "@/lib/modelPaidOperations";
import PageHeader from "@/components/PageHeader";
import { useT, type CtxT } from "@/lib/i18n";

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
  actual_quantity?: number;
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
  cutting_passport_id?: number | null;
  cutting_passport_no?: string | null;
  cutting_passports?: CuttingPassportOption[];
  planned_quantity: number;
  actual_quantity?: number;
  current_stage: string;
  sizes?: ProcessSize[];
  batches?: ProcessBatch[];
  stages: Stage[];
};

type CuttingPassportOption = {
  id: number;
  passport_no: string;
  lot_no?: string | null;
  date?: string | null;
};

type ProcessSize = {
  size: string;
  planned_quantity: number;
  completed_quantity: number;
};

type Department = {
  id: number;
  name: string;
  code?: string | null;
};

type SewingFlow = {
  id: number;
  name: string;
  code: string;
  is_active: boolean;
};

type LabelSewingLine = {
  id: number | null;
  code: string;
  name: string;
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
  actualQuantity: number;
  currentStage: string;
  serial: string;
  cuttingPassportId: number | null;
  cuttingPassportNo: string | null;
};

type LabelRow = {
  key: string;
  process: Process;
  batch: BatchOption;
  operation: PaidOperation;
  sewingLine: LabelSewingLine;
  size: string;
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

function normalizedReference(value: string | null | undefined): string {
  return String(value || "").toUpperCase().replace(/[^0-9A-Z]/g, "");
}

function cuttingPassportForBatch(
  process: Process,
  batchNo?: string | null,
  batchName?: string | null,
  serial?: string | null,
): CuttingPassportOption | null {
  const passports = process.cutting_passports || [];
  const references = [batchNo, batchName, serial].map(normalizedReference).filter(Boolean);
  return passports.find((passport) => {
    const lot = normalizedReference(passport.lot_no);
    return Boolean(lot && references.some((reference) => (
      reference === lot || reference.endsWith(lot) || lot.endsWith(reference)
    )));
  }) || passports[0] || (
    process.cutting_passport_no
      ? { id: Number(process.cutting_passport_id || 0), passport_no: process.cutting_passport_no }
      : null
  );
}

function batchesForProcess(process: Process | undefined, t: CtxT): BatchOption[] {
  if (!process) return [];
  const realBatches = Array.isArray(process.batches) ? process.batches : [];
  if (realBatches.length > 0) {
    return realBatches.map((batch) => {
      const serial = formatBatchSerial(batch, process.production_order_id);
      const passport = cuttingPassportForBatch(process, batch.batch_no, batch.name, serial);
      return {
        key: `batch-${batch.id}`,
        batchId: batch.id,
        batchNo: batch.batch_no,
        batchIndex: Number(batch.batch_index || 1),
        name: batch.name,
        plannedQuantity: numberOrZero(batch.planned_quantity),
        actualQuantity: numberOrZero(batch.actual_quantity),
        currentStage: batch.current_stage,
        serial,
        cuttingPassportId: passport?.id || null,
        cuttingPassportNo: passport?.passport_no || null,
      };
    });
  }

  const passport = cuttingPassportForBatch(process);
  return [
    {
      key: `po-${process.production_order_id}`,
      batchId: null,
      batchNo: null,
      batchIndex: 1,
      name: t("page.processQr.wholeOrder"),
      plannedQuantity: numberOrZero(process.planned_quantity),
      actualQuantity: numberOrZero(process.actual_quantity),
      currentStage: process.current_stage,
      serial: formatBatchSerial({ batch_index: 1 }, process.production_order_id),
      cuttingPassportId: passport?.id || null,
      cuttingPassportNo: passport?.passport_no || null,
    },
  ];
}

function batchDisplayName(batch: BatchOption): string {
  return batch.name ? `${batch.serial} - ${batch.name}` : batch.serial;
}

function payrollQuantity(batch: BatchOption): number {
  return Math.max(batch.plannedQuantity, batch.actualQuantity);
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

function workOrderIdForOperation(process: Process, operation: PaidOperation): number | null {
  const stage = process.stages.find((row) => row.operation === operation.section);
  return stage ? Number(stage.work_order_id) : null;
}

function workLabelId(
  process: Process,
  batch: BatchOption,
  operation: PaidOperation,
  sewingLine: LabelSewingLine,
  size: string,
  copyIndex: number,
): string {
  return [
    "PY",
    compactQrNumber(process.production_order_id),
    compactQrNumber(batch.batchId ?? batch.batchIndex),
    compactQrValue(batch.cuttingPassportNo).slice(0, 24),
    compactQrValue(operation.code).slice(0, 24),
    compactQrValue(sewingLine.code).slice(0, 24),
    compactQrValue(size).slice(0, 12),
    compactQrNumber(copyIndex),
  ].join(":");
}

function compactWorkPayload(
  process: Process,
  batch: BatchOption,
  operation: PaidOperation,
  sewingLine: LabelSewingLine,
  quantity: number,
  rate: number,
  currency: string,
  size: string,
  copyIndex: number,
): string {
  const workOrderId = workOrderIdForOperation(process, operation);
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
    compactQrNumber(process.sales_order_id),
    compactQrValue(process.sales_order_no),
    compactQrNumber(workOrderId),
    compactQrNumber(process.model_id),
    compactQrValue(workLabelId(process, batch, operation, sewingLine, size, copyIndex)),
    compactQrValue(size),
    compactQrNumber(sewingLine.id),
    compactQrValue(sewingLine.code),
    compactQrValue(sewingLine.name),
    compactQrNumber(batch.cuttingPassportId),
    compactQrValue(batch.cuttingPassportNo || process.cutting_passport_no),
  ].join("*");
}

function sewingLineDisplay(line: LabelSewingLine): string {
  return line.name && line.name !== line.code ? `${line.code} - ${line.name}` : line.code;
}

function employeeQrToken(employeeId: number): string {
  if (!Number.isInteger(employeeId) || employeeId <= 0 || employeeId >= 100_000_000) {
    throw new Error("Employee ID is outside the payroll QR range");
  }
  return `1${String(employeeId).padStart(8, "0")}`;
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

function distributeQuantityAcrossBatches(totalQuantity: number, batches: BatchOption[]): Map<string, number> {
  const total = Math.max(0, numberOrZero(totalQuantity));
  if (batches.length <= 1) return new Map(batches.map((batch) => [batch.key, roundedPieces(total)]));

  const rawWeights = batches.map((batch) => Math.max(0, payrollQuantity(batch)));
  const weightTotal = rawWeights.reduce((sum, weight) => sum + weight, 0);
  const weights = weightTotal > 0 ? rawWeights : batches.map(() => 1);
  const safeWeightTotal = weights.reduce((sum, weight) => sum + weight, 0);

  if (Number.isInteger(total)) {
    const rawShares = weights.map((weight) => (total * weight) / safeWeightTotal);
    const shares = rawShares.map(Math.floor);
    let remainder = Math.round(total - shares.reduce((sum, share) => sum + share, 0));
    const remainderOrder = rawShares
      .map((share, index) => ({ index, fraction: share - Math.floor(share) }))
      .sort((left, right) => right.fraction - left.fraction || left.index - right.index);
    for (let index = 0; index < remainder; index += 1) {
      shares[remainderOrder[index % remainderOrder.length].index] += 1;
    }
    return new Map(batches.map((batch, index) => [batch.key, shares[index]]));
  }

  const shares = weights.map((weight) => roundedPieces((total * weight) / safeWeightTotal));
  const difference = roundedPieces(total - shares.reduce((sum, share) => sum + share, 0));
  shares[shares.length - 1] = roundedPieces(shares[shares.length - 1] + difference);
  return new Map(batches.map((batch, index) => [batch.key, shares[index]]));
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

function splitQuantitiesForInputs(operation: PaidOperation): NumberInputValue[] {
  const copies = Math.max(1, Math.floor(numberOrZero(operation.copies) || 1));
  return Array.from({ length: copies }, (_, index) => operation.splitQuantities?.[index] ?? "");
}

export default function ProcessQrPage() {
  const { t } = useT();
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
  const { data: sewingFlows = [] } = useSWR<SewingFlow[]>("/api/sewing-flows", fetcher);
  const [query, setQuery] = useState("");
  const [selectedProcessId, setSelectedProcessId] = useState<number | null>(null);
  const [batchMode, setBatchMode] = useState<"selected" | "all">("selected");
  const [selectedBatchKey, setSelectedBatchKey] = useState("");
  const [currency, setCurrency] = useState("UZS");
  const [selectedSewingFlowKey, setSelectedSewingFlowKey] = useState("");
  const [sewingLineCode, setSewingLineCode] = useState("");
  const [sewingLineName, setSewingLineName] = useState("");
  const [sizeQuantityMode, setSizeQuantityMode] = useState<"same" | "custom">("custom");
  const [sameSizeQuantity, setSameSizeQuantity] = useState<NumberInputValue>(0);
  const [customSizeQuantities, setCustomSizeQuantities] = useState<Record<string, NumberInputValue>>({});
  const initializedSizeProcessId = useRef<number | null>(null);
  const [operations, setOperations] = useState<PaidOperation[]>(() => clonePaidOperations());
  const [loadedOperationsModelId, setLoadedOperationsModelId] = useState<number | null>(null);
  const [loadedOperationsSignature, setLoadedOperationsSignature] = useState("");
  const [operationModelDirty, setOperationModelDirty] = useState(false);
  const [savingModelOperations, setSavingModelOperations] = useState(false);
  const [modelSaveMsg, setModelSaveMsg] = useState("");
  const [employeeQuery, setEmployeeQuery] = useState("");
  const [employeeStatus, setEmployeeStatus] = useState<"active" | "all">("active");
  const [employeeCopies, setEmployeeCopies] = useState<NumberInputValue>(1);
  const [selectedEmployeeIds, setSelectedEmployeeIds] = useState<number[]>([]);
  const [employeeSelectionInitialized, setEmployeeSelectionInitialized] = useState(false);
  const [printMode, setPrintMode] = useState<"work" | "employees">("work");
  const [issuingLabels, setIssuingLabels] = useState(false);
  const [printError, setPrintError] = useState("");
  const [workQrTokens, setWorkQrTokens] = useState<Record<string, string>>({});

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
  const batchOptions = useMemo(() => batchesForProcess(selectedProcess, t), [selectedProcess, t]);
  const sizeOptions = useMemo<ProcessSize[]>(() => {
    const rows = selectedProcess?.sizes || [];
    if (rows.length > 0) return rows;
    return [{
      size: "-",
      planned_quantity: numberOrZero(selectedProcess?.planned_quantity),
      completed_quantity: 0,
    }];
  }, [selectedProcess]);
  const departmentById = useMemo(
    () => new Map(departments.map((department) => [Number(department.id), department])),
    [departments],
  );
  const activeSewingFlows = useMemo(
    () => sewingFlows.filter((flow) => flow.is_active),
    [sewingFlows],
  );
  const selectedSewingLine = useMemo<LabelSewingLine | null>(() => {
    const code = sewingLineCode.trim();
    if (!code) return null;
    const flowId = Number(selectedSewingFlowKey);
    return {
      id: Number.isFinite(flowId) && flowId > 0 ? flowId : null,
      code,
      name: sewingLineName.trim() || code,
    };
  }, [selectedSewingFlowKey, sewingLineCode, sewingLineName]);

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
    const processId = selectedProcess?.production_order_id ?? null;
    if (processId === initializedSizeProcessId.current) return;
    const planned = Object.fromEntries(sizeOptions.map((row) => [row.size, numberOrZero(row.planned_quantity)]));
    setCustomSizeQuantities(planned);
    setSameSizeQuantity(sizeOptions[0]?.planned_quantity || 0);
    initializedSizeProcessId.current = processId;
  }, [selectedProcess?.production_order_id, sizeOptions]);

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
    setModelSaveMsg(t("page.processQr.loadedModel", { model: selectedModel.code || selectedProcess?.model_code || t("common.model") }));
  }, [
    loadedOperationsModelId,
    loadedOperationsSignature,
    operationModelDirty,
    selectedModel,
    selectedModelId,
    selectedProcess?.model_code,
    t,
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
    const resetPrintMode = () => {
      document.body.classList.remove("process-qr-print-active");
      setPrintMode("work");
    };
    window.addEventListener("afterprint", resetPrintMode);
    return () => {
      document.body.classList.remove("process-qr-print-active");
      window.removeEventListener("afterprint", resetPrintMode);
    };
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
    if (!selectedProcess || !selectedSewingLine) return [];
    const rows: LabelRow[] = [];
    for (const batch of batchesToPrint) {
      for (const operation of selectedOperations) {
        for (const sizeOption of sizeOptions) {
          const totalSizeQuantity = sizeQuantityMode === "same"
            ? Math.max(0, numberOrZero(sameSizeQuantity))
            : Math.max(0, numberOrZero(customSizeQuantities[sizeOption.size]));
          const baseQuantity = distributeQuantityAcrossBatches(totalSizeQuantity, batchesToPrint).get(batch.key) ?? 0;
          if (baseQuantity <= 0) continue;
          const copies = Math.max(1, Math.floor(numberOrZero(operation.copies) || 1));
          const rate = Math.max(0, numberOrZero(operation.rate));
          const labelQuantities = quantitiesForOperationLabels(operation, baseQuantity, copies);
          for (let copyIndex = 1; copyIndex <= copies; copyIndex += 1) {
            const quantity = labelQuantities[copyIndex - 1] ?? 0;
            const payload = compactWorkPayload(
              selectedProcess,
              batch,
              operation,
              selectedSewingLine,
              quantity,
              rate,
              currency,
              sizeOption.size,
              copyIndex,
            );

            rows.push({
              key: `${batch.key}-${operation.id}-${sizeOption.size}-${copyIndex}`,
              process: selectedProcess,
              batch,
              operation,
              sewingLine: selectedSewingLine,
              size: sizeOption.size,
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
    }
    return rows;
  }, [batchesToPrint, currency, customSizeQuantities, sameSizeQuantity, selectedOperations, selectedProcess, selectedSewingLine, sizeOptions, sizeQuantityMode]);

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
          payload: employeeQrToken(Number(employee.id)),
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
    setModelSaveMsg(t("page.processQr.loadedModel", { model: selectedModel.code || selectedProcess?.model_code || t("common.model") }));
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
      setModelSaveMsg(t("page.processQr.savedModel", { model: selectedModel.code || selectedProcess?.model_code || "" }));
    } catch (err: any) {
      setModelSaveMsg(err?.message ? t("page.processQr.saveModelErrorDetail", { error: err.message }) : t("page.processQr.saveModelError"));
    } finally {
      setSavingModelOperations(false);
    }
  }

  function printSelectedMode(mode: "work" | "employees") {
    setPrintMode(mode);
    document.body.classList.add("process-qr-print-active");
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => window.print());
    });
  }

  async function printLabels() {
    if (labels.length === 0 || issuingLabels) return;
    setIssuingLabels(true);
    setPrintError("");
    try {
      const response = await api.post<{
        issued_count: number;
        labels: Array<{ label_uid: string; qr_token: string }>;
      }>("/api/payroll/qr-labels/issue", {
        labels: labels.map((label) => ({
          label_uid: workLabelId(label.process, label.batch, label.operation, label.sewingLine, label.size, label.copyIndex),
          payload: label.payload,
          production_order_id: label.process.production_order_id,
          sales_order_id: label.process.sales_order_id,
          work_order_id: workOrderIdForOperation(label.process, label.operation),
          production_batch_id: label.batch.batchId,
          model_id: label.process.model_id || null,
          production_no: label.process.production_no,
          sales_order_no: label.process.sales_order_no,
          batch_no: label.batch.batchNo || label.batch.serial,
          model_code: label.process.model_code,
          operation_section: label.operation.section,
          operation_code: label.operation.code,
          operation_name: label.operation.name,
          sewing_flow_id: label.sewingLine.id,
          sewing_line_code: label.sewingLine.code,
          sewing_line_name: label.sewingLine.name,
          cutting_passport_id: label.batch.cuttingPassportId,
          cutting_passport_no: label.batch.cuttingPassportNo || label.process.cutting_passport_no,
          size: label.size,
          copy_index: label.copyIndex,
          quantity: label.quantity,
          rate_per_piece: label.rate,
          currency: label.currency,
        })),
      }, 30_000);
      setWorkQrTokens((current) => ({
        ...current,
        ...Object.fromEntries(response.labels.map((row) => [row.label_uid, row.qr_token])),
      }));
      printSelectedMode("work");
    } catch (err: any) {
      setPrintError(err?.message || t("page.processQr.issueFailed"));
    } finally {
      setIssuingLabels(false);
    }
  }

  function printEmployeeBadges() {
    printSelectedMode("employees");
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
  const operationCounts = selectedOperations.map((operation) => {
    const operationLabels = labels.filter((label) => label.operation.id === operation.id);
    return {
      operation,
      labels: operationLabels.length,
      pieces: operationLabels.reduce((sum, label) => sum + label.quantity, 0),
      estimatedPay: operationLabels.reduce((sum, label) => sum + label.quantity * label.rate, 0),
    };
  });

  return (
    <div className={`process-qr-page print-mode-${printMode}`}>
      <div className="no-print">
        <PageHeader
          title={t("page.processQr.title")}
          subtitle={t("page.processQr.subtitle")}
          actions={(
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn" onClick={() => { mutate(); mutateEmployees(); }} title={t("page.processQr.refreshData")}>
                <RefreshCw />
                <span>{t("page.processQr.refresh")}</span>
              </button>
              <button type="button" className="btn" onClick={printEmployeeBadges} disabled={employeeBadgeRows.length === 0}>
                <Users />
                <span>{t("page.processQr.printEmployees")}</span>
              </button>
              <button type="button" className="btn btn-primary" onClick={printLabels} disabled={labels.length === 0 || issuingLabels}>
                {issuingLabels ? <RefreshCw className="animate-spin" /> : <Printer />}
                <span>{t("page.processQr.printLabels")}</span>
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
      {printError && (
        <div className="card mb-4 border-red-200 bg-red-50 p-3 text-sm text-red-700 no-print">
          {printError}
        </div>
      )}

      <div className="space-y-4 no-print">
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="card p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="app-card-title">{t("page.processQr.batchSource")}</h2>
              <p className="mt-1 text-xs text-[#8a8472]">{t("page.processQr.batchSourceHint")}</p>
            </div>
            <QrCode className="h-5 w-5 text-[#8a8472]" />
          </div>

          <label className="label">{t("page.processQr.searchOrder")}</label>
          <div className="mb-3 flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 shadow-sm">
            <Search className="h-4 w-4 text-[#8a8472]" />
            <input
              className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
              placeholder={t("page.processQr.orderSearchPlaceholder")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>

          <label className="label">{t("field.order")}</label>
          <select
            className="input mb-3"
            value={selectedProcess?.production_order_id || ""}
            onChange={(event) => setSelectedProcessId(Number(event.target.value))}
            disabled={isLoading || filteredProcesses.length === 0}
          >
            {filteredProcesses.map((process) => (
              <option key={process.production_order_id} value={process.production_order_id}>
                {orderReference(process, process.production_no)} - {process.model_code || t("page.processQr.noModel")}{process.customer_name ? ` - ${process.customer_name}` : ""}
              </option>
            ))}
          </select>

          <div className="mb-3 grid grid-cols-2 gap-2">
            <button
              type="button"
              className={`btn ${batchMode === "selected" ? "btn-primary" : ""}`}
              onClick={() => setBatchMode("selected")}
            >
              {t("page.processQr.oneBatch")}
            </button>
            <button
              type="button"
              className={`btn ${batchMode === "all" ? "btn-primary" : ""}`}
              onClick={() => setBatchMode("all")}
            >
              {t("page.processQr.allBatches")}
            </button>
          </div>

          {batchMode === "selected" && (
            <>
              <label className="label">{t("field.batch")}</label>
              <select
                className="input mb-3"
                value={selectedBatchKey}
                onChange={(event) => setSelectedBatchKey(event.target.value)}
                disabled={batchOptions.length === 0}
              >
                {batchOptions.map((batch) => (
                  <option key={batch.key} value={batch.key}>
                    {batchDisplayName(batch)} - {payrollQuantity(batch).toLocaleString()} {t("field.unitPcs")}
                  </option>
                ))}
              </select>
            </>
          )}

          <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className="label">{t("field.line")}</label>
              <select
                className="input"
                value={selectedSewingFlowKey}
                onChange={(event) => {
                  const value = event.target.value;
                  setSelectedSewingFlowKey(value);
                  const flow = activeSewingFlows.find((row) => String(row.id) === value);
                  setSewingLineCode(flow?.code || "");
                  setSewingLineName(flow?.name || "");
                }}
              >
                <option value="">{t("page.processQr.chooseSewingLine")}</option>
                {activeSewingFlows.map((flow) => (
                  <option key={flow.id} value={flow.id}>
                    {flow.code} - {flow.name}
                  </option>
                ))}
                <option value="custom">{t("page.processQr.customSewingLine")}</option>
              </select>
            </div>
            <div>
              <label className="label">{t("common.code")}</label>
              <input
                className="input font-mono"
                value={sewingLineCode}
                onChange={(event) => setSewingLineCode(event.target.value.toUpperCase())}
                disabled={!selectedSewingFlowKey}
                maxLength={64}
              />
            </div>
            <div>
              <label className="label">{t("field.lineName")}</label>
              <input
                className="input"
                value={sewingLineName}
                onChange={(event) => setSewingLineName(event.target.value)}
                disabled={!selectedSewingFlowKey}
                maxLength={255}
              />
            </div>
          </div>

          <label className="label">{t("page.processQr.rateCurrency")}</label>
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
                  {t("page.processQr.openOrder")}
                </Link>
              </div>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <dt className="text-[#8a8472]">{t("common.model")}</dt>
                <dd>{selectedProcess.model_code || "-"}</dd>
                <dt className="text-[#8a8472]">{t("common.customer")}</dt>
                <dd>{selectedProcess.customer_name || "-"}</dd>
                <dt className="text-[#8a8472]">{t("page.processQr.orderQty")}</dt>
                <dd>{Math.max(numberOrZero(selectedProcess.planned_quantity), numberOrZero(selectedProcess.actual_quantity)).toLocaleString()} {t("field.unitPcs")}</dd>
                {numberOrZero(selectedProcess.actual_quantity) > numberOrZero(selectedProcess.planned_quantity) && (
                  <>
                    <dt className="text-[#8a8472]">{t("field.plannedQty")}</dt>
                    <dd>{numberOrZero(selectedProcess.planned_quantity).toLocaleString()} {t("field.unitPcs")}</dd>
                  </>
                )}
                <dt className="text-[#8a8472]">{t("page.processQr.batches")}</dt>
                <dd>{batchOptions.length.toLocaleString()}</dd>
              </dl>
            </div>
          ) : (
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3 text-sm text-[#8a8472]">
              {isLoading ? t("page.processQr.loadingBatches") : t("page.processQr.noOrders")}
            </div>
          )}
          </section>

          <section className="card p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <h2 className="app-card-title">{t("page.processQr.sizeQuantities")}</h2>
                <p className="mt-1 text-xs text-[#8a8472]">{t("page.processQr.sizeQuantitiesHint")}</p>
              </div>
              <CheckSquare className="h-5 w-5 text-[#8a8472]" />
            </div>

            <div className="mb-4 grid grid-cols-2 gap-2">
              <button
                type="button"
                className={`btn ${sizeQuantityMode === "same" ? "btn-primary" : ""}`}
                onClick={() => setSizeQuantityMode("same")}
              >
                {t("page.processQr.sameForAllSizes")}
              </button>
              <button
                type="button"
                className={`btn ${sizeQuantityMode === "custom" ? "btn-primary" : ""}`}
                onClick={() => setSizeQuantityMode("custom")}
              >
                {t("page.processQr.customBySize")}
              </button>
            </div>

            {sizeQuantityMode === "same" ? (
              <div>
                <label className="label">{t("page.processQr.quantityPerSize")}</label>
                <input
                  className="input"
                  type="number"
                  min={0}
                  value={sameSizeQuantity}
                  onChange={(event) => setSameSizeQuantity(parseNumberInput(event.target.value))}
                />
                <div className="mt-2 text-xs text-[#8a8472]">
                  {t("page.processQr.sameSizeTotal", {
                    sizes: sizeOptions.length,
                    total: (numberOrZero(sameSizeQuantity) * sizeOptions.length).toLocaleString(),
                  })}
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {sizeOptions.map((row) => (
                  <div key={row.size}>
                    <label className="label">{row.size}</label>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      value={customSizeQuantities[row.size] ?? ""}
                      onChange={(event) => setCustomSizeQuantities((current) => ({
                        ...current,
                        [row.size]: parseNumberInput(event.target.value),
                      }))}
                    />
                    <div className="mt-1 text-[11px] text-[#8a8472]">
                      {t("page.processQr.orderSizeQty", { quantity: numberOrZero(row.planned_quantity).toLocaleString() })}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <section className="card p-4">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="app-card-title">{t("page.processQr.paidOperations")}</h2>
              <p className="mt-1 text-xs text-[#8a8472]">{t("page.processQr.paidOperationsHint")}</p>
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
                title={t("page.processQr.loadModelTitle")}
              >
                <RefreshCw />
                <span>{t("page.processQr.loadModel")}</span>
              </button>
              <button
                type="button"
                className="btn"
                onClick={saveOperationsToModel}
                disabled={!selectedModelId || !selectedModel || savingModelOperations}
                title={t("page.processQr.saveModelTitle")}
              >
                <Save />
                <span>{savingModelOperations ? t("common.saving") : t("page.processQr.saveToModel")}</span>
              </button>
              <button type="button" className="btn" onClick={addOperation}>
                <Plus />
                <span>{t("page.processQr.addOperation")}</span>
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="table min-w-[940px]">
              <thead>
                <tr>
                  <th className="w-12">{t("page.processQr.use")}</th>
                  <th>{t("field.section")}</th>
                  <th>{t("common.code")}</th>
                  <th>{t("page.processQr.operationName")}</th>
                  <th>{t("page.processQr.ratePerPiece")}</th>
                  <th>{t("page.processQr.copies")}</th>
                  <th>{t("page.processQr.divide")}</th>
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
                        <option value="sewing">{t("statusValue.sewing")}</option>
                        <option value="pressing">{t("page.processQr.pressing")}</option>
                        <option value="packaging">{t("statusValue.packaging")}</option>
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
                        onChange={(event) => updateOperation(operation.id, { copies: parseNumberInput(event.target.value) })}
                      />
                    </td>
                    <td>
                      <div className="min-w-[260px] space-y-2">
                        <select
                          className="input"
                          value={operation.splitMode}
                          onChange={(event) => updateOperation(operation.id, { splitMode: event.target.value as SplitMode })}
                        >
                          <option value="none">{t("page.processQr.noDivide")}</option>
                          <option value="equal">{t("page.processQr.equalDivide")}</option>
                          <option value="custom">{t("page.processQr.customDivide")}</option>
                        </select>
                        {operation.splitMode === "equal" && (
                          <div className="text-xs text-[#8a8472]">
                            {t("page.processQr.equalDivideHint")}
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
                                    nextQuantities[index] = parseNumberInput(event.target.value);
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
                        title={t("page.processQr.removeOperation")}
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

          <div className="mt-4 overflow-x-auto rounded-md border border-[#ecebe3]">
            <div className="border-b border-[#ecebe3] bg-[#f8f6ef] px-3 py-2 text-sm font-semibold text-[#14110b]">
              {t("page.processQr.processCounts")}
            </div>
            <table className="table min-w-[620px]">
              <thead>
                <tr>
                  <th>{t("page.processQr.operationName")}</th>
                  <th>{t("field.section")}</th>
                  <th className="text-right">{t("page.processQr.labels")}</th>
                  <th className="text-right">{t("page.processQr.countedPieces")}</th>
                  <th className="text-right">{t("page.processQr.estimatedPay")}</th>
                </tr>
              </thead>
              <tbody>
                {operationCounts.map((row) => (
                  <tr key={`count-${row.operation.id}`}>
                    <td>
                      <div className="font-medium text-[#14110b]">{row.operation.name}</div>
                      <div className="text-xs font-mono text-[#8a8472]">{row.operation.code}</div>
                    </td>
                    <td>{t(`page.processQr.section.${row.operation.section}`)}</td>
                    <td className="text-right tabular-nums">{row.labels.toLocaleString()}</td>
                    <td className="text-right tabular-nums">{row.pieces.toLocaleString()}</td>
                    <td className="text-right tabular-nums">{money(row.estimatedPay, currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
              <div className="label">{t("page.processQr.labels")}</div>
              <div className="text-2xl font-semibold">{labels.length.toLocaleString()}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
              <div className="label">{t("page.processQr.countedPieces")}</div>
              <div className="text-2xl font-semibold">{totalPieces.toLocaleString()}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3">
              <div className="label">{t("page.processQr.estimatedPay")}</div>
              <div className="text-2xl font-semibold">{money(totalEstimatedPay, currency)}</div>
            </div>
          </div>
        </section>
      </div>

      <section className="mt-4 card p-4 no-print">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="app-card-title">{t("page.processQr.employeeBadges")}</h2>
            <p className="mt-1 text-xs text-[#8a8472]">{t("page.processQr.employeeBadgesHint")}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn" onClick={selectVisibleEmployees}>
              {t("page.processQr.selectVisible")}
            </button>
            <button type="button" className="btn" onClick={clearVisibleEmployees}>
              {t("page.processQr.clearVisible")}
            </button>
            <button type="button" className="btn btn-primary" onClick={printEmployeeBadges} disabled={employeeBadgeRows.length === 0}>
              <Printer />
              <span>{t("page.processQr.printEmployees")}</span>
            </button>
          </div>
        </div>

        <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-[minmax(260px,1fr)_180px_140px]">
          <div>
            <label className="label">{t("page.processQr.searchEmployee")}</label>
            <div className="flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 shadow-sm">
              <Search className="h-4 w-4 text-[#8a8472]" />
              <input
                className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
                placeholder={t("page.processQr.employeeSearchPlaceholder")}
                value={employeeQuery}
                onChange={(event) => setEmployeeQuery(event.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="label">{t("page.processQr.employees")}</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                className={`btn ${employeeStatus === "active" ? "btn-primary" : ""}`}
                onClick={() => setEmployeeStatus("active")}
              >
                {t("field.active")}
              </button>
              <button
                type="button"
                className={`btn ${employeeStatus === "all" ? "btn-primary" : ""}`}
                onClick={() => setEmployeeStatus("all")}
              >
                {t("common.all")}
              </button>
            </div>
          </div>
          <div>
            <label className="label">{t("page.processQr.copies")}</label>
            <input
              className="input"
              type="number"
              min={1}
              value={employeeCopies}
              onChange={(event) => setEmployeeCopies(parseNumberInput(event.target.value))}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
          <div className="overflow-x-auto">
            <table className="table min-w-[760px]">
              <thead>
                <tr>
                  <th className="w-12">{t("page.processQr.use")}</th>
                  <th>{t("page.processQr.employee")}</th>
                  <th>{t("field.department")}</th>
                  <th>{t("field.position")}</th>
                  <th>{t("common.status")}</th>
                </tr>
              </thead>
              <tbody>
                {employeesLoading && (
                  <tr>
                    <td colSpan={5} className="text-sm text-[#8a8472]">{t("page.processQr.loadingEmployees")}</td>
                  </tr>
                )}
                {!employeesLoading && filteredEmployees.length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-sm text-[#8a8472]">{t("page.processQr.noEmployees")}</td>
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
                          {t(`statusValue.${employee.status}`)}
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
                <div className="label">{t("page.processQr.selected")}</div>
                <div className="text-2xl font-semibold">{employeeBadgeRows.length.toLocaleString()}</div>
              </div>
              <div>
                <div className="label">{t("page.processQr.visible")}</div>
                <div className="text-2xl font-semibold">{filteredEmployees.length.toLocaleString()}</div>
              </div>
            </div>
            <div className="text-xs text-[#8a8472]">
              {t("page.processQr.employeeQrHint")}
            </div>
          </div>
        </div>
      </section>

      <section className="mt-5 print-sheet employee-print-section">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 no-print">
          <div>
            <h2 className="app-card-title">{t("page.processQr.employeePreview")}</h2>
            <p className="mt-1 text-xs text-[#8a8472]">{t("page.processQr.employeePreviewHint")}</p>
          </div>
          <div className="inline-flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 text-xs text-[#56503f]">
            <Users className="h-4 w-4" />
            {t("page.processQr.employeeBadgeCount", { count: employeeBadgeRows.length.toLocaleString() })}
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
            {t("page.processQr.selectEmployeeHint")}
          </div>
        )}
      </section>

      <section className="mt-5 print-sheet work-print-section">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 no-print">
          <div>
            <h2 className="app-card-title">{t("page.processQr.labelPreview")}</h2>
            <p className="mt-1 text-xs text-[#8a8472]">
              {t("page.processQr.workQrHint")}
            </p>
          </div>
          <div className="inline-flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 text-xs text-[#56503f]">
            <CheckSquare className="h-4 w-4" />
            {t("page.processQr.batchGroupCount", { count: batchesToPrint.length.toLocaleString() })}
          </div>
        </div>

        {labels.length > 0 ? (
          <div className="label-grid">
            {labels.map((label) => (
              <ProcessLabel
                key={label.key}
                label={label}
                qrToken={workQrTokens[workLabelId(label.process, label.batch, label.operation, label.sewingLine, label.size, label.copyIndex)] || ""}
              />
            ))}
          </div>
        ) : (
          <div className="card p-6 text-sm text-[#8a8472] no-print">
            {t("page.processQr.selectOrderHint")}
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
            size: 60mm 40mm;
            margin: 0;
          }

          html,
          body {
            width: 60mm !important;
            min-width: 60mm !important;
            min-height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: visible !important;
          }

          body {
            background: #fff !important;
          }

          body * {
            visibility: hidden !important;
          }

          aside,
          header,
          .no-print {
            display: none !important;
          }

          main {
            padding: 0 !important;
            margin: 0 !important;
            width: 60mm !important;
            min-width: 60mm !important;
          }

          .process-qr-page.print-mode-work .employee-print-section,
          .process-qr-page.print-mode-employees .work-print-section {
            display: none !important;
          }

          .process-qr-page,
          .process-qr-page .print-sheet,
          .process-qr-page .print-sheet *,
          .process-label,
          .process-label * {
            visibility: visible !important;
          }

          .process-qr-page {
            display: block !important;
            position: absolute !important;
            inset: 0 auto auto 0 !important;
            width: 60mm !important;
            min-width: 60mm !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: visible !important;
            background: #fff !important;
          }

          .process-qr-page > :not(.print-sheet) {
            display: none !important;
          }

          .print-sheet {
            display: block !important;
            margin: 0 !important;
            padding: 0 !important;
            width: 60mm !important;
          }

          .label-grid {
            display: block;
            font-size: 0;
            width: 60mm !important;
          }

          .process-label {
            display: flex !important;
            width: 60mm !important;
            height: 40mm !important;
            min-height: 40mm !important;
            max-height: 40mm !important;
            margin: 0 !important;
            padding: 1.5mm !important;
            box-sizing: border-box !important;
            break-inside: avoid;
            page-break-inside: avoid;
            border: 0;
            border-radius: 0;
            box-shadow: none !important;
            overflow: hidden !important;
            font-size: 6pt;
            line-height: 1;
          }

          .process-label + .process-label {
            break-before: page;
            page-break-before: always;
          }

          .process-label__qr {
            height: 22mm !important;
            width: 22mm !important;
            flex: 0 0 22mm !important;
            align-self: center !important;
          }

          .process-label__title {
            max-width: 100% !important;
            overflow: hidden !important;
            font-size: 7.2pt !important;
            line-height: 1 !important;
            white-space: nowrap !important;
            text-overflow: ellipsis !important;
          }

          .process-label__body {
            min-height: 0 !important;
            overflow: hidden !important;
            align-items: stretch !important;
            gap: 1mm !important;
          }

          .process-label__details {
            min-width: 0 !important;
            overflow: hidden !important;
            font-size: 5.6pt !important;
            line-height: 1.03 !important;
          }

          .process-label__line {
            grid-template-columns: 9mm minmax(0, 1fr) !important;
            min-height: 2.05mm !important;
            gap: 0.7mm !important;
            align-items: baseline !important;
            overflow: hidden !important;
          }

          .process-label__line > span:first-child {
            min-width: 0 !important;
            overflow: hidden !important;
            white-space: nowrap !important;
          }

          .process-label__value {
            min-width: 0 !important;
            max-width: 100% !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: clip !important;
            word-break: normal !important;
          }

          .process-label__value--wrap {
            display: -webkit-box !important;
            max-height: 4.1mm !important;
            white-space: normal !important;
            overflow-wrap: break-word !important;
            -webkit-box-orient: vertical !important;
            -webkit-line-clamp: 2 !important;
          }

          .process-label__footer {
            min-height: 2.5mm !important;
            margin-top: 0.4mm !important;
            padding-top: 0.4mm !important;
            overflow: hidden !important;
            font-size: 5.5pt !important;
            line-height: 1 !important;
            letter-spacing: 0 !important;
            white-space: nowrap !important;
          }

          .process-label__badge {
            display: none !important;
          }
        }
      `}</style>
    </div>
  );
}

function EmployeeBadge({ row }: { row: EmployeeBadgeRow }) {
  const { t } = useT();
  const { employee, departmentName, payload } = row;
  return (
    <article className="process-label process-label--employee flex flex-col p-3">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="process-label__title break-words text-[13px] font-bold leading-tight text-[#111]">
            {employee.full_name}
          </div>
        </div>
        <span className={`process-label__badge badge shrink-0 ${employee.status === "active" ? "badge-green" : "badge-red"}`}>
          {t(`statusValue.${employee.status}`)}
        </span>
      </div>

      <div className="process-label__body flex min-h-0 flex-1 gap-2">
        <div className="process-label__details min-w-0 flex-1 text-[10px] leading-tight">
          <LabelLine label="ID" value={`EMP-${String(employee.id).padStart(4, "0")}`} strong />
          <LabelLine label={t("field.dept")} value={departmentName} wrap />
          <LabelLine label={t("field.role")} value={employee.position || "-"} wrap />
        </div>
        <ProcessQrImage payload={payload} alt={t("page.processQr.employeeQrAlt")} />
      </div>

      <div className="process-label__footer mt-1 flex items-center justify-end gap-2 border-t border-[#e8e3d6] pt-1 text-[9px] font-semibold text-[#6b6251]">
        <span className="shrink-0">EMP-{String(employee.id).padStart(4, "0")}</span>
      </div>
    </article>
  );
}

function ProcessLabel({ label, qrToken }: { label: LabelRow; qrToken: string }) {
  const { t } = useT();
  const { process, batch, operation, sewingLine, size, quantity, rate, currency, copyIndex, copyCount, splitMode } = label;

  return (
    <article className="process-label process-label--work flex flex-col p-3">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="process-label__title break-words text-[13px] font-bold leading-tight text-[#111]">
            {operation.name}
          </div>
        </div>
        <span className={`process-label__badge badge shrink-0 ${SECTION_BADGES[operation.section]}`}>
          {t(`page.processQr.section.${operation.section}`)}
        </span>
      </div>

      <div className="process-label__body flex min-h-0 flex-1 gap-2">
        <div className="process-label__details min-w-0 flex-1 text-[10px] leading-tight">
          <LabelLine label={t("common.model")} value={process.model_code || "-"} />
          <LabelLine label={t("page.processQr.kroyNo")} value={batch.cuttingPassportNo || process.cutting_passport_no || "-"} strong />
          <LabelLine label={t("field.batch")} value={batch.serial} />
          <LabelLine label={t("page.processQr.line")} value={sewingLineDisplay(sewingLine)} strong wrap />
          <LabelLine label={t("field.size")} value={size} strong />
          <LabelLine label={t("field.qty")} value={`${quantity.toLocaleString()} ${t("field.unitPcs")}`} strong />
          {splitMode !== "none" && <LabelLine label={t("page.processQr.part")} value={`${copyIndex}/${copyCount}`} strong />}
          <LabelLine label={t("page.processQr.rate")} value={rate ? `${rate.toLocaleString()} ${currency}` : "-"} />
        </div>
        <ProcessQrImage payload={qrToken} alt={t("page.processQr.workQrAlt")} />
      </div>

      <div className="process-label__footer mt-1 flex items-center justify-between gap-2 border-t border-[#e8e3d6] pt-1 text-[9px] font-semibold text-[#6b6251]">
        <span className="truncate">{operation.code}</span>
        <span className="shrink-0">{batch.serial}</span>
      </div>
    </article>
  );
}

function LabelLine({
  label,
  value,
  strong = false,
  wrap = false,
}: {
  label: string;
  value: string;
  strong?: boolean;
  wrap?: boolean;
}) {
  return (
    <div className="process-label__line grid grid-cols-[33px_minmax(0,1fr)] gap-1">
      <span className="text-[#7a725f]">{label}</span>
      <span className={`process-label__value ${wrap ? "process-label__value--wrap" : ""} ${strong ? "font-bold" : "font-medium"}`}>{value}</span>
    </div>
  );
}

function ProcessQrImage({ payload, alt }: { payload: string; alt?: string }) {
  const { t } = useT();
  const [src, setSrc] = useState("");

  useEffect(() => {
    let active = true;
    if (!payload) {
      setSrc("");
      return () => {
        active = false;
      };
    }
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

  return <img className="process-label__qr" src={src} alt={alt || t("page.processQr.payrollQrAlt")} />;
}
