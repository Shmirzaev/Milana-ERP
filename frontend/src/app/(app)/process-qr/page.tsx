"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import QRCode from "qrcode";
import {
  ArrowDown,
  ArrowUp,
  CheckSquare,
  ChevronDown,
  Pencil,
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
import { buildOperationLabelTokens } from "@/lib/processQrLabelIdentity";
import { useMe } from "@/lib/auth";
import {
  clonePaidOperations,
  createPaidOperation,
  materializeLegacyPaidOperations,
  paidOperationFactoryFromDepartmentCode,
  paidOperationMatchesFactory,
  paidOperationsFromDetails,
  SECTION_BADGES,
  serializePaidOperations,
  type PaidOperation,
  type PaidOperationFactory,
  type SectionCode,
  type SplitMode,
} from "@/lib/modelPaidOperations";
import PageHeader from "@/components/PageHeader";
import { useDialogs } from "@/components/DialogProvider";
import Modal from "@/components/Modal";
import { useT, type CtxT } from "@/lib/i18n";
import { modelVariantOption, type ModelVariantModel } from "@/lib/modelVariants";

const FACTORY_LABEL_KEYS: Record<PaidOperationFactory, string> = {
  milana: "factory.milana",
  besttex: "factory.besttex",
  eco_cotton: "factory.ecoCotton",
};

const FACTORY_SHORT_CODES: Record<PaidOperationFactory, string> = {
  milana: "MIL",
  besttex: "BST",
  eco_cotton: "ECO",
};

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

type CollapsibleSection = "paidOperations" | "employees" | "employeePreview" | "workPreview";

type ProcessBatch = {
  id: number;
  batch_no: string | null;
  batch_index: number;
  name: string | null;
  planned_quantity: number;
  actual_quantity?: number;
  sewing_completed_quantity?: number;
  sewing_unallocated_quantity?: number;
  sewing_sizes?: ProcessSize[];
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
  sewing_completed_quantity?: number;
  sewing_unallocated_quantity?: number;
  current_stage: string;
  sizes?: ProcessSize[];
  batches?: ProcessBatch[];
  stages: Stage[];
  sewing_factories?: FactoryRef[];
  is_manual?: boolean;
  manual_kroy_no?: string | null;
};

type ManualModel = ModelVariantModel & {
  code: string;
  name: string;
  description?: string | null;
  brand_id?: number | null;
  collection_id?: number | null;
  product_type?: string | null;
  season?: string | null;
  constructor_employee_id?: number | null;
  designer_employee_id?: number | null;
  details_json?: Record<string, any> | null;
  sizes?: Array<{ id: number; size: string }>;
  status?: string | null;
  sam_minutes?: number | null;
};

type ManualModelSearchResponse = {
  items?: ManualModel[];
  has_more?: boolean;
};

type FactoryRef = {
  code: string;
  name: string;
};

type CuttingPassportOption = {
  id: number;
  passport_no: string;
  lot_no?: string | null;
  date?: string | null;
};

type ProcessSize = {
  size: string;
  planned_quantity?: number;
  completed_quantity?: number;
  sewing_completed_quantity?: number;
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
  employee_no?: string | null;
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
  sewingCompletedQuantity: number;
  sewingSizes: ProcessSize[];
  currentStage: string;
  serial: string;
  cuttingPassportId: number | null;
  cuttingPassportNo: string | null;
};

type LabelRow = {
  key: string;
  labelUid: string;
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

type IssuedLabelRow = {
  id: number;
  label_uid: string;
  qr_token: string;
  payload: string | null;
  production_order_id: number | null;
  production_no: string | null;
  sales_order_no: string | null;
  batch_no: string | null;
  model_code: string | null;
  operation_section: string | null;
  operation_code: string | null;
  operation_name: string | null;
  sewing_line_code: string | null;
  sewing_line_name: string | null;
  cutting_passport_no: string | null;
  size: string | null;
  copy_index: number;
  quantity: number;
  rate_per_piece: number;
  currency: string;
  status: "available" | "scanned" | "superseded";
  payroll_record_id: number | null;
  issued_at: string;
  last_scanned_at: string | null;
  return_count: number;
  superseded_at: string | null;
  superseded_by: number | null;
  split_from_label_id: number | null;
};

type LabelCorrectionMode = "edit" | "split";

type LabelCorrectionForm = {
  label: IssuedLabelRow;
  mode: LabelCorrectionMode;
  operationName: string;
  ratePerPiece: string;
  quantities: string[];
};

type IssuedLabelsResponse = {
  items: IssuedLabelRow[];
  total: number;
  available_count: number;
  scanned_count: number;
};

type PreparedPrintLabel = {
  label: IssuedLabelRow;
  qrImage: string;
  operationNumber: number;
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
  if (process.is_manual) {
    const kroyNo = String(process.manual_kroy_no || "").trim();
    return [{
      key: `manual-${process.model_id || 0}-${manualReferenceToken(kroyNo)}`,
      batchId: null,
      batchNo: kroyNo || null,
      batchIndex: 1,
      name: t("page.processQr.manualOrder"),
      plannedQuantity: 0,
      actualQuantity: 0,
      sewingCompletedQuantity: 0,
      sewingSizes: [],
      currentStage: "sewing",
      serial: kroyNo || "-",
      cuttingPassportId: null,
      cuttingPassportNo: kroyNo || null,
    }];
  }
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
        sewingCompletedQuantity: numberOrZero(batch.sewing_completed_quantity),
        sewingSizes: batch.sewing_sizes || [],
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
      sewingCompletedQuantity: numberOrZero(process.sewing_completed_quantity),
      sewingSizes: process.sizes || [],
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
  return batch.sewingCompletedQuantity;
}

function sameSize(left: string, right: string): boolean {
  return left.trim().toLocaleLowerCase() === right.trim().toLocaleLowerCase();
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

function manualReferenceToken(value: string): string {
  const text = value.trim().toUpperCase().replace(/\s+/g, " ");
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  const readable = compactQrValue(text, "KROY").replace(/\s+/g, "-").slice(0, 24);
  return `${readable}-${(hash >>> 0).toString(36).toUpperCase()}`;
}

function manualProductionReference(modelId: number, kroyNo: string): string {
  return `MAN-${modelId}-${manualReferenceToken(kroyNo)}`.slice(0, 64);
}

function workOrderIdForOperation(process: Process, operation: PaidOperation): number | null {
  const stage = process.stages.find((row) => row.operation === operation.section);
  return stage ? Number(stage.work_order_id) : null;
}

function workLabelId(
  process: Process,
  batch: BatchOption,
  operation: PaidOperation,
  operationLabelToken: string,
  sewingLine: LabelSewingLine,
  size: string,
  copyIndex: number,
): string {
  if (process.is_manual) {
    return [
      "PY",
      "MAN",
      compactQrNumber(process.model_id),
      manualReferenceToken(process.manual_kroy_no || ""),
      compactQrValue(operationLabelToken).slice(0, 24),
      FACTORY_SHORT_CODES[operation.sewingFactory || "milana"],
      compactQrValue(sewingLine.code).slice(0, 24),
      compactQrValue(size).slice(0, 12),
      compactQrNumber(copyIndex),
    ].join(":");
  }
  return [
    "PY",
    compactQrNumber(process.production_order_id),
    compactQrNumber(batch.batchId ?? batch.batchIndex),
    compactQrValue(batch.cuttingPassportNo).slice(0, 24),
    compactQrValue(operationLabelToken).slice(0, 24),
    FACTORY_SHORT_CODES[operation.sewingFactory || "milana"],
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
  labelUid: string,
): string {
  const workOrderId = workOrderIdForOperation(process, operation);
  return [
    "MW2",
    compactQrNumber(process.is_manual ? null : process.production_order_id),
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
    compactQrValue(labelUid),
    compactQrValue(size),
    compactQrNumber(sewingLine.id),
    compactQrValue(sewingLine.code),
    compactQrValue(sewingLine.name),
    compactQrNumber(batch.cuttingPassportId),
    compactQrValue(batch.cuttingPassportNo || process.cutting_passport_no),
    FACTORY_SHORT_CODES[operation.sewingFactory || "milana"],
  ].join("*");
}

function sewingLineDisplay(line: LabelSewingLine): string {
  return line.name && line.name !== line.code ? `${line.code} - ${line.name}` : line.code;
}

function sewingLinePrintText(code: string | null, name: string | null): string {
  const codeText = String(code || "").trim();
  const nameText = String(name || "").trim();
  if (!nameText || nameText === codeText) return codeText || "-";

  const nameParts = nameText.split(/\s+/).filter(Boolean);
  if (nameParts.length === 1) return [codeText, nameText].filter(Boolean).join("\n");

  const suffixIndex = nameParts.findIndex((part, index) => index > 0 && part === "-");
  const lastNameIndex = suffixIndex > 0 ? suffixIndex - 1 : nameParts.length - 1;
  const firstLine = [codeText, ...nameParts.slice(0, lastNameIndex)].filter(Boolean).join(" ");
  const secondLine = nameParts.slice(lastNameIndex).join(" ");
  return [firstLine, secondLine].filter(Boolean).join("\n") || "-";
}

function qrDataUrl(payload: string): Promise<string> {
  return QRCode.toDataURL(payload, {
    errorCorrectionLevel: "L",
    margin: 1,
    width: 240,
    color: {
      dark: "#111111",
      light: "#ffffff",
    },
  });
}

function employeeNumber(employee: Employee): string {
  const configuredNumber = String(employee.employee_no || "").trim();
  return configuredNumber || `EMP-${String(employee.id).padStart(4, "0")}`;
}

function roundedPieces(value: number): number {
  return Math.max(0, Math.round((value + Number.EPSILON) * 100) / 100);
}

const NAMED_SIZE_ORDER: Record<string, number> = {
  XXS: 0,
  XS: 1,
  S: 2,
  M: 3,
  L: 4,
  XL: 5,
  XXL: 6,
  XXXL: 7,
};

function normalizedSizeName(value: string): string {
  return value.trim().toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function namedSizeRank(value: string): number {
  const normalized = normalizedSizeName(value);
  if (NAMED_SIZE_ORDER[normalized] !== undefined) return NAMED_SIZE_ORDER[normalized];
  const xlMatch = normalized.match(/^(\d+)XL/);
  if (xlMatch) return 4 + Number(xlMatch[1]);
  return Number.MAX_SAFE_INTEGER;
}

function compareGarmentSizes(left: string, right: string): number {
  const leftNumbers = left.match(/\d+(?:[.,]\d+)?/g) || [];
  const rightNumbers = right.match(/\d+(?:[.,]\d+)?/g) || [];
  const leftNumber = leftNumbers.at(-1);
  const rightNumber = rightNumbers.at(-1);
  if (leftNumber && rightNumber) {
    const difference = Number(leftNumber.replace(",", ".")) - Number(rightNumber.replace(",", "."));
    if (difference !== 0) return difference;
  } else if (leftNumber || rightNumber) {
    return leftNumber ? -1 : 1;
  }

  const rankDifference = namedSizeRank(left) - namedSizeRank(right);
  if (rankDifference !== 0) return rankDifference;
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" });
}

function operationKey(code: string | null | undefined, name: string | null | undefined): string {
  return `${String(code || "").trim().toUpperCase()}::${String(name || "").trim().toLocaleLowerCase()}`;
}

function operationNumberForLabel(label: IssuedLabelRow, numbers: Map<string, number>): number {
  return (
    numbers.get(operationKey(label.operation_code, label.operation_name))
    ?? numbers.get(operationKey(label.operation_code, null))
    ?? numbers.get(operationKey(null, label.operation_name))
    ?? 1
  );
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
  const dialogs = useDialogs();
  const { t } = useT();
  const { me } = useMe();
  const accountPaidOperationFactory = useMemo<PaidOperationFactory>(
    () => paidOperationFactoryFromDepartmentCode(me?.factory_code) || "milana",
    [me?.factory_code],
  );
  const selectablePaidOperationFactories = useMemo<PaidOperationFactory[]>(
    () => [accountPaidOperationFactory],
    [accountPaidOperationFactory],
  );
  const [query, setQuery] = useState("");
  const [processSearch, setProcessSearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setProcessSearch(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);
  const processUrl = `/api/process-tracking?page_size=100&sewing_completed_only=true${
    processSearch ? `&q=${encodeURIComponent(processSearch)}` : ""
  }`;
  const { data = [], error, isLoading, mutate } = useSWR<Process[]>(
    processUrl,
    fetcher,
    {
      refreshInterval: 60_000,
      refreshWhenHidden: false,
      refreshWhenOffline: false,
      revalidateOnFocus: true,
      keepPreviousData: true,
    },
  );
  const { data: employees = [], error: employeesError, isLoading: employeesLoading, mutate: mutateEmployees } = useSWR<Employee[]>(
    "/api/employees",
    fetcher,
  );
  const { data: departments = [] } = useSWR<Department[]>("/api/departments", fetcher);
  const { data: sewingFlows = [] } = useSWR<SewingFlow[]>("/api/sewing-flows", fetcher);
  const [sourceMode, setSourceMode] = useState<"erp" | "manual">("erp");
  const [selectedProcessId, setSelectedProcessId] = useState<number | null>(null);
  const [manualModelQuery, setManualModelQuery] = useState("");
  const [manualModelId, setManualModelId] = useState<number | null>(null);
  const [manualKroyNo, setManualKroyNo] = useState("");
  const [batchMode, setBatchMode] = useState<"selected" | "all">("selected");
  const [selectedBatchKey, setSelectedBatchKey] = useState("");
  const [currency, setCurrency] = useState("UZS");
  const [selectedSewingFlowKey, setSelectedSewingFlowKey] = useState("");
  const [sewingLineCode, setSewingLineCode] = useState("");
  const [sewingLineName, setSewingLineName] = useState("");
  const [sizeQuantityMode, setSizeQuantityMode] = useState<"same" | "custom">("custom");
  const [sameSizeQuantity, setSameSizeQuantity] = useState<NumberInputValue>(0);
  const [customSizeQuantities, setCustomSizeQuantities] = useState<Record<string, NumberInputValue>>({});
  const initializedSizeSourceKey = useRef("");
  const [operations, setOperations] = useState<PaidOperation[]>(() => clonePaidOperations());
  const [loadedOperationsModelId, setLoadedOperationsModelId] = useState<number | null>(null);
  const [loadedOperationsSignature, setLoadedOperationsSignature] = useState("");
  const [operationModelDirty, setOperationModelDirty] = useState(false);
  const [savingModelOperations, setSavingModelOperations] = useState(false);
  const [modelSaveMsg, setModelSaveMsg] = useState("");
  const [printPaidOperationFactory, setPrintPaidOperationFactory] = useState<PaidOperationFactory>("milana");
  const [employeeQuery, setEmployeeQuery] = useState("");
  const [employeeStatus, setEmployeeStatus] = useState<"active" | "all">("active");
  const [employeeCopies, setEmployeeCopies] = useState<NumberInputValue>(1);
  const [selectedEmployeeIds, setSelectedEmployeeIds] = useState<number[]>([]);
  const [employeeSelectionInitialized, setEmployeeSelectionInitialized] = useState(false);
  const [printMode, setPrintMode] = useState<"work" | "employees">("work");
  const [issuingLabels, setIssuingLabels] = useState(false);
  const [deletingSize, setDeletingSize] = useState<string | null>(null);
  const [labelCorrection, setLabelCorrection] = useState<LabelCorrectionForm | null>(null);
  const [savingLabelCorrection, setSavingLabelCorrection] = useState(false);
  const [editedLabelIds, setEditedLabelIds] = useState<number[]>([]);
  const [printError, setPrintError] = useState("");
  const [issueNotice, setIssueNotice] = useState("");
  const [preparingPrint, setPreparingPrint] = useState(false);
  const [workLabelsToPrint, setWorkLabelsToPrint] = useState<PreparedPrintLabel[]>([]);
  const issuedLabelsSectionRef = useRef<HTMLElement | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Record<CollapsibleSection, boolean>>({
    paidOperations: true,
    employees: true,
    employeePreview: true,
    workPreview: true,
  });

  useEffect(() => {
    setPrintPaidOperationFactory(accountPaidOperationFactory);
  }, [accountPaidOperationFactory]);

  const filteredProcesses = data;
  const manualModelSearch = manualModelQuery.trim();
  const manualModelsUrl = sourceMode === "manual" && manualModelSearch
    ? `/api/model-options?search=${encodeURIComponent(manualModelSearch)}&page=1&page_size=50`
    : null;
  const {
    data: manualModelSearchResponse,
    error: manualModelsError,
    isLoading: manualModelsLoading,
    mutate: mutateManualModels,
  } = useSWR<ManualModelSearchResponse>(manualModelsUrl, fetcher, { keepPreviousData: true });
  const manualModels = useMemo(
    () => manualModelSearchResponse?.items || [],
    [manualModelSearchResponse?.items],
  );

  const selectedTrackedProcess = useMemo(() => {
    if (selectedProcessId == null) return filteredProcesses[0] || data[0];
    return (
      filteredProcesses.find((process) => process.production_order_id === selectedProcessId)
      || filteredProcesses[0]
      || data.find((process) => process.production_order_id === selectedProcessId)
      || data[0]
    );
  }, [data, filteredProcesses, selectedProcessId]);

  const selectedModelId = sourceMode === "manual"
    ? manualModelId
    : selectedTrackedProcess?.model_id
      ? Number(selectedTrackedProcess.model_id)
      : null;
  const { data: selectedModel, mutate: mutateSelectedModel } = useSWR<ManualModel>(
    selectedModelId ? `/api/models/${selectedModelId}` : null,
    fetcher,
  );
  const manualProcess = useMemo<Process | undefined>(() => {
    if (!selectedModelId || !selectedModel) return undefined;
    const kroyNo = manualKroyNo.trim();
    const sizes = (selectedModel.sizes || [])
      .map((row) => String(row.size || "").trim())
      .filter(Boolean)
      .map((size) => ({ size, planned_quantity: 0, completed_quantity: 0 }));
    return {
      production_order_id: 0,
      production_no: kroyNo ? manualProductionReference(selectedModelId, kroyNo) : "",
      order_no: null,
      sales_order_id: null,
      sales_order_no: null,
      customer_name: null,
      model_id: selectedModelId,
      model_code: selectedModel.code,
      model_name: selectedModel.name,
      cutting_passport_id: null,
      cutting_passport_no: kroyNo || null,
      planned_quantity: 0,
      actual_quantity: 0,
      current_stage: "sewing",
      sizes,
      batches: [],
      stages: [],
      sewing_factories: [],
      is_manual: true,
      manual_kroy_no: kroyNo,
    };
  }, [manualKroyNo, selectedModel, selectedModelId]);
  const selectedProcess = sourceMode === "manual" ? manualProcess : selectedTrackedProcess;
  const issuedLabelsUrl = selectedProcess?.is_manual
    ? selectedProcess.production_no
      ? `/api/payroll/qr-labels?order_no=${encodeURIComponent(selectedProcess.production_no)}&include_superseded=true&limit=5000`
      : null
    : selectedProcess?.production_order_id
      ? `/api/payroll/qr-labels?production_order_id=${selectedProcess.production_order_id}&include_superseded=true&limit=5000`
      : null;
  const {
    data: issuedLabelsResponse,
    error: issuedLabelsError,
    isLoading: issuedLabelsLoading,
    mutate: mutateIssuedLabels,
  } = useSWR<IssuedLabelsResponse>(issuedLabelsUrl, fetcher);
  const issuedLabels = useMemo(
    () => issuedLabelsResponse?.items || [],
    [issuedLabelsResponse?.items],
  );
  const activeIssuedLabels = useMemo(
    () => issuedLabels.filter((label) => label.status !== "superseded"),
    [issuedLabels],
  );

  const inferredPaidOperationFactory = useMemo<PaidOperationFactory | undefined>(() => {
    if (selectedProcess?.is_manual && selectedModel) {
      const manualFactories = new Set(
        materializeLegacyPaidOperations(paidOperationsFromDetails(selectedModel.details_json))
          .map((operation) => operation.sewingFactory || "milana"),
      );
      if (manualFactories.size === 1) return Array.from(manualFactories)[0];
    }
    const factories = selectedProcess?.sewing_factories || [];
    if (factories.length !== 1) return undefined;
    return paidOperationFactoryFromDepartmentCode(factories[0].code);
  }, [selectedModel, selectedProcess?.is_manual, selectedProcess?.sewing_factories]);

  useEffect(() => {
    if (accountPaidOperationFactory) {
      setPrintPaidOperationFactory(accountPaidOperationFactory);
      return;
    }
    if (inferredPaidOperationFactory) setPrintPaidOperationFactory(inferredPaidOperationFactory);
  }, [accountPaidOperationFactory, inferredPaidOperationFactory, selectedProcess?.production_order_id]);
  const batchOptions = useMemo(() => batchesForProcess(selectedProcess, t), [selectedProcess, t]);
  const selectedBatchOption = useMemo(
    () => batchOptions.find((batch) => batch.key === selectedBatchKey),
    [batchOptions, selectedBatchKey],
  );
  const sizeOptions = useMemo<ProcessSize[]>(() => {
    const rows = !selectedProcess?.is_manual && batchMode === "selected" && selectedBatchOption
      ? selectedBatchOption.sewingSizes
      : selectedProcess?.sizes || [];
    if (rows.length > 0) return [...rows].sort((left, right) => compareGarmentSizes(left.size, right.size));
    if (selectedProcess?.is_manual) return [];
    return [{
      size: "-",
      planned_quantity: 0,
      completed_quantity: 0,
      sewing_completed_quantity: numberOrZero(selectedProcess?.sewing_completed_quantity),
    }];
  }, [batchMode, selectedBatchOption, selectedProcess]);
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
          employee.employee_no,
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
    if (sourceMode !== "manual" || manualModels.length === 0) return;
    if (manualModelId && manualModels.some((model) => Number(model.id) === manualModelId)) return;
    setManualModelId(Number(manualModels[0].id));
  }, [manualModelId, manualModels, sourceMode]);

  useEffect(() => {
    if (sourceMode !== "erp") return;
    if (
      filteredProcesses.length > 0
      && (selectedProcessId == null || !filteredProcesses.some((process) => process.production_order_id === selectedProcessId))
    ) {
      setSelectedProcessId(filteredProcesses[0].production_order_id);
    }
  }, [filteredProcesses, selectedProcessId, sourceMode]);

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
    const sourceKey = selectedProcess?.is_manual
      ? `manual:${selectedProcess.model_id || 0}`
      : selectedProcess
        ? `erp:${selectedProcess.production_order_id}:${batchMode}:${selectedBatchKey}`
        : "";
    if (sourceKey === initializedSizeSourceKey.current) return;
    const quantities = Object.fromEntries(sizeOptions.map((row) => [
      row.size,
      selectedProcess?.is_manual
        ? numberOrZero(row.planned_quantity)
        : numberOrZero(row.sewing_completed_quantity),
    ]));
    setCustomSizeQuantities(quantities);
    setSameSizeQuantity(selectedProcess?.is_manual ? sizeOptions[0]?.planned_quantity || 0 : 0);
    if (!selectedProcess?.is_manual) setSizeQuantityMode("custom");
    initializedSizeSourceKey.current = sourceKey;
  }, [batchMode, selectedBatchKey, selectedProcess, sizeOptions]);

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

    const nextOperations = materializeLegacyPaidOperations(paidOperationsFromDetails(selectedModel.details_json));
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
      setWorkLabelsToPrint([]);
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

  const factoryOperations = useMemo(
    () => operations.filter((operation) => paidOperationMatchesFactory(operation, printPaidOperationFactory)),
    [operations, printPaidOperationFactory],
  );

  const operationLabelTokens = useMemo(
    () => buildOperationLabelTokens(factoryOperations),
    [factoryOperations],
  );

  const selectedOperations = useMemo(
    () => factoryOperations.filter((operation) => (
      operation.selected
      && operation.code.trim()
      && operation.name.trim()
    )),
    [factoryOperations],
  );

  const labels = useMemo<LabelRow[]>(() => {
    if (!selectedProcess || !selectedSewingLine) return [];
    if (selectedProcess.is_manual && !selectedProcess.manual_kroy_no?.trim()) return [];
    const rows: LabelRow[] = [];
    for (const sizeOption of sizeOptions) {
      for (const batch of batchesToPrint) {
        for (const operation of selectedOperations) {
          const totalSizeQuantity = sizeQuantityMode === "same"
            ? Math.max(0, numberOrZero(sameSizeQuantity))
            : Math.max(0, numberOrZero(customSizeQuantities[sizeOption.size]));
          const baseQuantity = selectedProcess.is_manual
            ? distributeQuantityAcrossBatches(totalSizeQuantity, batchesToPrint).get(batch.key) ?? 0
            : numberOrZero(
                batch.sewingSizes.find((row) => sameSize(row.size, sizeOption.size))?.sewing_completed_quantity,
              );
          if (baseQuantity <= 0) continue;
          const copies = Math.max(1, Math.floor(numberOrZero(operation.copies) || 1));
          const rate = Math.max(0, numberOrZero(operation.rate));
          const labelQuantities = quantitiesForOperationLabels(operation, baseQuantity, copies);
          for (let copyIndex = 1; copyIndex <= copies; copyIndex += 1) {
            const quantity = labelQuantities[copyIndex - 1] ?? 0;
            const operationLabelToken = operationLabelTokens.get(operation.id) || operation.code;
            const labelUid = workLabelId(
              selectedProcess,
              batch,
              operation,
              operationLabelToken,
              selectedSewingLine,
              sizeOption.size,
              copyIndex,
            );
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
              labelUid,
            );

            rows.push({
              key: `${batch.key}-${operation.id}-${sizeOption.size}-${copyIndex}`,
              labelUid,
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
  }, [batchesToPrint, currency, customSizeQuantities, operationLabelTokens, sameSizeQuantity, selectedOperations, selectedProcess, selectedSewingLine, sizeOptions, sizeQuantityMode]);

  const issuedLabelUids = useMemo(
    () => new Set(issuedLabels.map((label) => label.label_uid)),
    [issuedLabels],
  );
  const unissuedLabels = useMemo(
    () => labels.filter((label) => !issuedLabelUids.has(label.labelUid)),
    [issuedLabelUids, labels],
  );
  const issuedOperationNumbers = useMemo(() => {
    const numbers = new Map<string, number>();
    const register = (code: string | null | undefined, name: string | null | undefined, number: number) => {
      const keys = [
        operationKey(code, name),
        operationKey(code, null),
        operationKey(null, name),
      ];
      for (const key of keys) {
        if (key !== "::" && !numbers.has(key)) numbers.set(key, number);
      }
    };

    factoryOperations.forEach((operation, index) => register(operation.code, operation.name, index + 1));
    let nextNumber = factoryOperations.length + 1;
    for (const label of [...activeIssuedLabels].sort((left, right) => left.id - right.id)) {
      const exactKey = operationKey(label.operation_code, label.operation_name);
      const codeKey = operationKey(label.operation_code, null);
      const nameKey = operationKey(null, label.operation_name);
      if (numbers.has(exactKey) || numbers.has(codeKey) || numbers.has(nameKey)) continue;
      register(label.operation_code, label.operation_name, nextNumber);
      nextNumber += 1;
    }
    return numbers;
  }, [activeIssuedLabels, factoryOperations]);
  const issuedLabelsBySize = useMemo(() => {
    const groups = new Map<string, IssuedLabelRow[]>();
    for (const label of activeIssuedLabels) {
      const size = label.size?.trim() || "-";
      groups.set(size, [...(groups.get(size) || []), label]);
    }
    const configuredOrder = new Map(sizeOptions.map((row, index) => [row.size, index]));
    return Array.from(groups.entries()).map(([size, sizeLabels]) => [
      size,
      [...sizeLabels].sort((left, right) => (
        operationNumberForLabel(left, issuedOperationNumbers) - operationNumberForLabel(right, issuedOperationNumbers)
        || left.copy_index - right.copy_index
        || left.id - right.id
      )),
    ] as [string, IssuedLabelRow[]]).sort(([left], [right]) => {
      const leftIndex = configuredOrder.get(left);
      const rightIndex = configuredOrder.get(right);
      if (leftIndex !== undefined || rightIndex !== undefined) {
        return (leftIndex ?? Number.MAX_SAFE_INTEGER) - (rightIndex ?? Number.MAX_SAFE_INTEGER);
      }
      return compareGarmentSizes(left, right);
    });
  }, [activeIssuedLabels, issuedOperationNumbers, sizeOptions]);
  const orderedIssuedLabels = useMemo(
    () => issuedLabelsBySize.flatMap(([, sizeLabels]) => sizeLabels),
    [issuedLabelsBySize],
  );
  const editedIssuedLabels = useMemo(() => {
    const editedIds = new Set(editedLabelIds);
    return orderedIssuedLabels.filter((label) => editedIds.has(label.id));
  }, [editedLabelIds, orderedIssuedLabels]);

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
          payload: employeeNumber(employee),
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
      createPaidOperation("op", selectedProcess?.planned_quantity || 0, printPaidOperationFactory),
    ]);
  }

  function removeOperation(id: string) {
    markOperationsDirty();
    setOperations((current) => current.filter((operation) => operation.id !== id));
  }

  function moveOperation(id: string, direction: -1 | 1) {
    markOperationsDirty();
    setOperations((current) => {
      const visible = current.filter((operation) => paidOperationMatchesFactory(operation, printPaidOperationFactory));
      const visibleIndex = visible.findIndex((operation) => operation.id === id);
      const target = visible[visibleIndex + direction];
      if (visibleIndex < 0 || !target) return current;

      const fromIndex = current.findIndex((operation) => operation.id === id);
      const toIndex = current.findIndex((operation) => operation.id === target.id);
      const reordered = [...current];
      [reordered[fromIndex], reordered[toIndex]] = [reordered[toIndex], reordered[fromIndex]];

      let sourceOrder = 0;
      return reordered.map((operation) => {
        if (!paidOperationMatchesFactory(operation, printPaidOperationFactory)) return operation;
        sourceOrder += 1;
        return { ...operation, sourceOrder };
      });
    });
  }

  function loadOperationsFromSelectedModel() {
    if (!selectedModel || !selectedModelId) return;
    const nextOperations = materializeLegacyPaidOperations(paidOperationsFromDetails(selectedModel.details_json));
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
      await api.patch(`/api/models/${selectedModelId}/paid-operations`, {
        paid_operations: nextOperations,
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

  async function issueLabels() {
    if (unissuedLabels.length === 0 || issuingLabels || issuedLabelsLoading) return;
    setIssuingLabels(true);
    setPrintError("");
    setIssueNotice("");
    try {
      const response = await api.post<{
        issued_count: number;
        created_count: number;
        existing_count: number;
        labels: Array<{ label_uid: string; qr_token: string }>;
      }>("/api/payroll/qr-labels/issue", {
        labels: unissuedLabels.map((label) => ({
          label_uid: label.labelUid,
          payload: label.payload,
          production_order_id: label.process.is_manual ? null : label.process.production_order_id,
          sales_order_id: label.process.is_manual ? null : label.process.sales_order_id,
          work_order_id: workOrderIdForOperation(label.process, label.operation),
          production_batch_id: label.process.is_manual ? null : label.batch.batchId,
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
      await mutateIssuedLabels();
      setIssueNotice(t("page.processQr.labelsIssued", { count: response.created_count.toLocaleString() }));
      window.requestAnimationFrame(() => {
        issuedLabelsSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (err: any) {
      setPrintError(err?.message || t("page.processQr.issueFailed"));
    } finally {
      setIssuingLabels(false);
    }
  }

  async function deleteIssuedSize(size: string, sizeLabels: IssuedLabelRow[]) {
    if (deletingSize || sizeLabels.length === 0) return;
    const eligible = sizeLabels.every((label) => (
      label.status === "available"
      && !label.payroll_record_id
      && !label.last_scanned_at
      && Number(label.return_count || 0) === 0
    ));
    if (!eligible) {
      await dialogs.notify({
        title: t("page.processQr.deleteSizeBlockedTitle"),
        message: t("page.processQr.deleteSizeBlocked"),
      });
      return;
    }

    const confirmed = await dialogs.ask({
      title: t("page.processQr.deleteSizeTitle", { size }),
      message: t("page.processQr.deleteSizeConfirm", {
        size,
        count: sizeLabels.length.toLocaleString(),
      }),
      confirmText: t("page.processQr.deleteSize"),
      tone: "danger",
    });
    if (!confirmed) return;

    setDeletingSize(size);
    setPrintError("");
    try {
      const response = await api.post<{ deleted_count: number; size: string }>(
        "/api/payroll/qr-labels/delete-batch",
        { size, label_ids: sizeLabels.map((label) => label.id) },
        30_000,
      );
      setIssueNotice(t("page.processQr.sizeDeleted", {
        size: response.size,
        count: response.deleted_count.toLocaleString(),
      }));
      await mutateIssuedLabels();
    } catch (err: any) {
      setPrintError(err?.message || t("page.processQr.deleteSizeFailed"));
    } finally {
      setDeletingSize(null);
    }
  }

  function canCorrectIssuedLabel(label: IssuedLabelRow): boolean {
    return (
      label.status === "available"
      && !label.payroll_record_id
      && !label.last_scanned_at
      && Number(label.return_count || 0) === 0
    );
  }

  function openLabelCorrection(label: IssuedLabelRow) {
    if (!canCorrectIssuedLabel(label)) return;
    const initialSplit = equalSplitQuantities(Math.max(1, Number(label.quantity)), 2);
    setPrintError("");
    setLabelCorrection({
      label,
      mode: "edit",
      operationName: label.operation_name || label.operation_code || "",
      ratePerPiece: String(Number(label.rate_per_piece) || 0),
      quantities: initialSplit.map(String),
    });
  }

  function setLabelCorrectionMode(mode: LabelCorrectionMode) {
    setLabelCorrection((current) => current ? { ...current, mode } : current);
  }

  function updateSplitQuantity(index: number, value: string) {
    setLabelCorrection((current) => {
      if (!current) return current;
      const quantities = [...current.quantities];
      quantities[index] = value;
      return { ...current, quantities };
    });
  }

  function addSplitPart() {
    setLabelCorrection((current) => current ? { ...current, quantities: [...current.quantities, ""] } : current);
  }

  function removeSplitPart(index: number) {
    setLabelCorrection((current) => {
      if (!current || current.quantities.length <= 2) return current;
      return { ...current, quantities: current.quantities.filter((_, itemIndex) => itemIndex !== index) };
    });
  }

  async function saveLabelCorrection() {
    if (!labelCorrection || savingLabelCorrection) return;
    const operationName = labelCorrection.operationName.trim();
    const ratePerPiece = Number(labelCorrection.ratePerPiece);
    if (!operationName || !Number.isFinite(ratePerPiece) || ratePerPiece < 0) {
      setPrintError(t("page.processQr.editLabelInvalid"));
      return;
    }

    const commonPayload = {
      operation_name: operationName,
      rate_per_piece: ratePerPiece,
    };
    setSavingLabelCorrection(true);
    setPrintError("");
    try {
      if (labelCorrection.mode === "edit") {
        const updated = await api.patch<IssuedLabelRow>(
          `/api/payroll/qr-labels/${labelCorrection.label.id}`,
          commonPayload,
        );
        setEditedLabelIds((current) => Array.from(new Set([...current, updated.id])));
        setIssueNotice(t("page.processQr.labelEdited"));
      } else {
        const quantities = labelCorrection.quantities.map((value) => Number(value));
        const originalQuantity = Number(labelCorrection.label.quantity);
        const splitTotal = quantities.reduce((sum, quantity) => sum + quantity, 0);
        if (
          quantities.length < 2
          || quantities.some((quantity) => !Number.isInteger(quantity) || quantity <= 0)
          || splitTotal !== originalQuantity
        ) {
          setPrintError(t("page.processQr.splitQuantityMismatch", { quantity: originalQuantity.toLocaleString() }));
          return;
        }
        const response = await api.post<{ superseded_label_id: number; labels: IssuedLabelRow[] }>(
          `/api/payroll/qr-labels/${labelCorrection.label.id}/split`,
          { ...commonPayload, quantities },
          30_000,
        );
        setEditedLabelIds((current) => Array.from(new Set([
          ...current.filter((id) => id !== response.superseded_label_id),
          ...response.labels.map((label) => label.id),
        ])));
        setIssueNotice(t("page.processQr.labelSplit", { count: response.labels.length.toLocaleString() }));
      }
      setLabelCorrection(null);
      await mutateIssuedLabels();
    } catch (err: any) {
      setPrintError(err?.message || t("page.processQr.editLabelFailed"));
    } finally {
      setSavingLabelCorrection(false);
    }
  }

  async function printIssuedLabels(rows: IssuedLabelRow[]) {
    if (rows.length === 0 || preparingPrint) return;
    setPrintError("");
    setPreparingPrint(true);
    try {
      const prepared = await Promise.all(rows.map(async (label) => ({
        label,
        qrImage: await qrDataUrl(label.qr_token),
        operationNumber: operationNumberForLabel(label, issuedOperationNumbers),
      })));
      setWorkLabelsToPrint(prepared);
      printSelectedMode("work");
    } catch (err: any) {
      setPrintError(err?.message || t("page.processQr.printPreparationFailed"));
    } finally {
      setPreparingPrint(false);
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

  function sectionToggle(section: CollapsibleSection) {
    const collapsed = collapsedSections[section];
    return (
      <button
        type="button"
        className="btn"
        aria-expanded={!collapsed}
        onClick={() => setCollapsedSections((current) => ({ ...current, [section]: !current[section] }))}
      >
        <span>{t(collapsed ? "nav.expandMenu" : "nav.collapseMenu")}</span>
        <ChevronDown className={`h-4 w-4 transition-transform ${collapsed ? "-rotate-90" : ""}`} />
      </button>
    );
  }

  return (
    <div className={`process-qr-page print-mode-${printMode}`}>
      <div className="no-print">
        <PageHeader
          title={t("page.processQr.title")}
          subtitle={t("page.processQr.subtitle")}
          actions={(
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn" onClick={() => { mutate(); mutateEmployees(); mutateManualModels(); mutateSelectedModel(); }} title={t("page.processQr.refreshData")}>
                <RefreshCw />
                <span>{t("page.processQr.refresh")}</span>
              </button>
              <button type="button" className="btn" onClick={printEmployeeBadges} disabled={employeeBadgeRows.length === 0}>
                <Users />
                <span>{t("page.processQr.printEmployees")}</span>
              </button>
              <button type="button" className="btn btn-primary" onClick={issueLabels} disabled={unissuedLabels.length === 0 || issuingLabels || issuedLabelsLoading}>
                {issuingLabels ? <RefreshCw className="animate-spin" /> : <Printer />}
                <span>{t(issuingLabels ? "page.processQr.issuingLabels" : "page.processQr.issueLabels")}</span>
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
      {issuedLabelsError && (
        <div className="card mb-4 border-red-200 bg-red-50 p-3 text-sm text-red-700 no-print">
          {String((issuedLabelsError as Error).message || issuedLabelsError)}
        </div>
      )}
      {issueNotice && (
        <div className="card mb-4 border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800 no-print">
          {issueNotice}
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

          <div className="mb-4 grid grid-cols-2 gap-2">
            <button
              type="button"
              className={`btn ${sourceMode === "erp" ? "btn-primary" : ""}`}
              onClick={() => setSourceMode("erp")}
            >
              {t("page.processQr.erpOrder")}
            </button>
            <button
              type="button"
              className={`btn ${sourceMode === "manual" ? "btn-primary" : ""}`}
              onClick={() => setSourceMode("manual")}
            >
              {t("page.processQr.manualOrder")}
            </button>
          </div>

          {sourceMode === "erp" ? (
            <>
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
              <p className="mb-3 text-xs text-[#8a8472]">{t("page.processQr.closedSewingOrdersHint")}</p>

              <label className="label">{t("field.order")}</label>
              <select
                className="input mb-3"
                value={selectedTrackedProcess?.production_order_id || ""}
                onChange={(event) => setSelectedProcessId(Number(event.target.value))}
                disabled={isLoading || filteredProcesses.length === 0}
              >
                {filteredProcesses.length === 0 && (
                  <option value="">{t("page.processQr.noClosedSewingOrders")}</option>
                )}
                {filteredProcesses.map((process) => (
                  <option key={process.production_order_id} value={process.production_order_id}>
                    {orderReference(process, process.production_no)} - {process.model_code || t("page.processQr.noModel")}{process.customer_name ? ` - ${process.customer_name}` : ""} - {numberOrZero(process.sewing_completed_quantity).toLocaleString()} {t("field.unitPcs")}
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
            </>
          ) : (
            <>
              <label className="label">{t("page.processQr.searchVariant")}</label>
              <div className="mb-3 flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 shadow-sm">
                <Search className="h-4 w-4 text-[#8a8472]" />
                <input
                  className="w-full bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
                  placeholder={t("page.processQr.variantSearchPlaceholder")}
                  value={manualModelQuery}
                  onChange={(event) => setManualModelQuery(event.target.value)}
                />
              </div>

              <label className="label">{t("page.processQr.modelVariant")}</label>
              <select
                className="input mb-3"
                value={manualModelId || ""}
                onChange={(event) => setManualModelId(Number(event.target.value))}
                disabled={!manualModelSearch || manualModelsLoading || manualModels.length === 0}
              >
                {!manualModelSearch && <option value="">{t("page.processQr.typeVariantFirst")}</option>}
                {manualModelSearch && manualModelsLoading && <option value="">{t("common.loading")}</option>}
                {manualModelSearch && !manualModelsLoading && manualModels.length === 0 && (
                  <option value="">{t("page.processQr.noVariantsFound")}</option>
                )}
                {manualModels.map((model) => {
                  const option = modelVariantOption(model);
                  return (
                    <option key={model.id} value={model.id}>
                      {option.variantNo || "-"} - {option.code || model.code}{model.name ? ` - ${model.name}` : ""}
                    </option>
                  );
                })}
              </select>

              <label className="label">{t("page.processQr.kroyNo")}</label>
              <input
                className="input mb-3 font-mono"
                value={manualKroyNo}
                onChange={(event) => setManualKroyNo(event.target.value)}
                placeholder={t("page.processQr.kroyNoPlaceholder")}
                maxLength={64}
              />
              {manualModelsError && (
                <div className="mb-3 text-xs text-red-700">
                  {String((manualModelsError as Error).message || manualModelsError)}
                </div>
              )}
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

          {selectedProcess?.is_manual ? (
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3 text-sm">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="font-medium">{t("page.processQr.manualOrder")}</span>
                {selectedModelId && (
                  <Link className="text-xs text-[#c2410c] hover:underline" href={`/models/${selectedModelId}`}>
                    {t("page.processQr.openModel")}
                  </Link>
                )}
              </div>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                <dt className="text-[#8a8472]">{t("common.model")}</dt>
                <dd>{selectedProcess.model_code || "-"}</dd>
                <dt className="text-[#8a8472]">{t("field.variantNo")}</dt>
                <dd>{selectedModel ? modelVariantOption(selectedModel).variantNo || "-" : "-"}</dd>
                <dt className="text-[#8a8472]">{t("page.processQr.kroyNo")}</dt>
                <dd>{selectedProcess.manual_kroy_no || "-"}</dd>
                <dt className="text-[#8a8472]">{t("page.processQr.sizes")}</dt>
                <dd>{(selectedProcess.sizes || []).length.toLocaleString()}</dd>
                <dt className="text-[#8a8472]">{t("page.processQr.manualReference")}</dt>
                <dd className="break-all font-mono">{selectedProcess.production_no || "-"}</dd>
              </dl>
            </div>
          ) : selectedProcess ? (
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
                <dt className="text-[#8a8472]">{t("page.processQr.sewingEnteredQty")}</dt>
                <dd className="font-semibold">{numberOrZero(selectedProcess.sewing_completed_quantity).toLocaleString()} {t("field.unitPcs")}</dd>
                <dt className="text-[#8a8472]">{t("page.processQr.batches")}</dt>
                <dd>{batchOptions.length.toLocaleString()}</dd>
              </dl>
            </div>
          ) : (
            <div className="rounded-md border border-[#ecebe3] bg-[#f8f6ef] p-3 text-sm text-[#8a8472]">
              {sourceMode === "manual"
                ? t("page.processQr.manualOrderHint")
                : isLoading
                  ? t("page.processQr.loadingBatches")
                  : t("page.processQr.noClosedSewingOrders")}
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

            {selectedProcess?.is_manual && (
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
            )}

            {selectedProcess?.is_manual && sizeOptions.length === 0 && (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                {t("page.processQr.manualModelHasNoSizes")}
              </div>
            )}

            {selectedProcess?.is_manual && sizeOptions.length > 0 && sizeQuantityMode === "same" ? (
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
            ) : sizeOptions.length > 0 ? (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                {sizeOptions.map((row) => (
                  <div key={row.size}>
                    <label className="label">{row.size}</label>
                    <input
                      className="input"
                      type="number"
                      min={0}
                      value={customSizeQuantities[row.size] ?? ""}
                      readOnly={!selectedProcess?.is_manual}
                      onChange={(event) => setCustomSizeQuantities((current) => ({
                        ...current,
                        [row.size]: parseNumberInput(event.target.value),
                      }))}
                    />
                    <div className="mt-1 text-[11px] text-[#8a8472]">
                      {selectedProcess?.is_manual
                        ? t("page.processQr.orderSizeQty", { quantity: numberOrZero(row.planned_quantity).toLocaleString() })
                        : t("page.processQr.sewingEnteredSizeQty", { quantity: numberOrZero(row.sewing_completed_quantity).toLocaleString() })}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
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
            <div className="flex flex-wrap items-end gap-2">
              <label className="min-w-[180px]">
                <span className="label">{t("page.modelDetail.paidOperationFactory")}</span>
                <select
                  className="input"
                  value={printPaidOperationFactory}
                  onChange={(event) => setPrintPaidOperationFactory(event.target.value as PaidOperationFactory)}
                  disabled={selectablePaidOperationFactories.length === 1}
                >
                  {selectablePaidOperationFactories.map((factory) => (
                    <option key={factory} value={factory}>{t(FACTORY_LABEL_KEYS[factory])}</option>
                  ))}
                </select>
              </label>
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
              {sectionToggle("paidOperations")}
            </div>
          </div>

          <div className={`process-qr-collapsible ${collapsedSections.paidOperations ? "is-collapsed" : ""}`}>
          <div className="overflow-x-auto">
            <table className="table min-w-[850px]">
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
                {factoryOperations.map((operation, operationIndex) => {
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
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          className="icon-btn"
                          title={t("page.processQr.moveOperationUp")}
                          aria-label={t("page.processQr.moveOperationUp")}
                          onClick={() => moveOperation(operation.id, -1)}
                          disabled={operationIndex === 0}
                        >
                          <ArrowUp />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          title={t("page.processQr.moveOperationDown")}
                          aria-label={t("page.processQr.moveOperationDown")}
                          onClick={() => moveOperation(operation.id, 1)}
                          disabled={operationIndex === factoryOperations.length - 1}
                        >
                          <ArrowDown />
                        </button>
                        <button
                          type="button"
                          className="icon-btn"
                          title={t("page.processQr.removeOperation")}
                          onClick={() => removeOperation(operation.id)}
                          disabled={factoryOperations.length <= 1}
                        >
                          <Trash2 />
                        </button>
                      </div>
                    </td>
                  </tr>
                  );
                })}
                {factoryOperations.length === 0 && (
                  <tr>
                    <td colSpan={8} className="py-6 text-center text-sm text-[#8a8472]">
                      {t("page.modelDetail.noFactoryPaidOperations")}
                    </td>
                  </tr>
                )}
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
            {sectionToggle("employees")}
          </div>
        </div>

        <div className={`process-qr-collapsible ${collapsedSections.employees ? "is-collapsed" : ""}`}>
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
                        <div className="text-xs text-[#8a8472]">{employeeNumber(employee)}</div>
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
        </div>
      </section>

      <section className="mt-5 print-sheet employee-print-section">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 no-print">
          <div>
            <h2 className="app-card-title">{t("page.processQr.employeePreview")}</h2>
            <p className="mt-1 text-xs text-[#8a8472]">{t("page.processQr.employeePreviewHint")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 text-xs text-[#56503f]">
              <Users className="h-4 w-4" />
              {t("page.processQr.employeeBadgeCount", { count: employeeBadgeRows.length.toLocaleString() })}
            </div>
            {sectionToggle("employeePreview")}
          </div>
        </div>

        <div className={`process-qr-collapsible ${collapsedSections.employeePreview ? "is-collapsed" : ""}`}>
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
        </div>
      </section>

      <section className="mt-5 no-print">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2 no-print">
          <div>
            <h2 className="app-card-title">{t("page.processQr.labelsReadyToIssue")}</h2>
            <p className="mt-1 text-xs text-[#8a8472]">
              {t("page.processQr.labelsReadyToIssueHint")}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 py-2 text-xs text-[#56503f]">
              <CheckSquare className="h-4 w-4" />
              {t("page.processQr.unissuedLabelCount", { count: unissuedLabels.length.toLocaleString() })}
            </div>
            <button type="button" className="btn btn-primary" onClick={issueLabels} disabled={unissuedLabels.length === 0 || issuingLabels || issuedLabelsLoading}>
              {issuingLabels ? <RefreshCw className="animate-spin" /> : <QrCode />}
              <span>{t(issuingLabels ? "page.processQr.issuingLabels" : "page.processQr.issueLabels")}</span>
            </button>
            {sectionToggle("workPreview")}
          </div>
        </div>

        <div className={`process-qr-collapsible ${collapsedSections.workPreview ? "is-collapsed" : ""}`}>
        {unissuedLabels.length > 0 ? (
          <div className="label-grid">
            {unissuedLabels.map((label) => (
              <ProcessLabel
                key={label.key}
                label={label}
                qrToken=""
              />
            ))}
          </div>
        ) : labels.length > 0 && !issuedLabelsLoading ? (
          <div className="card border-emerald-200 bg-emerald-50 p-6 text-sm text-emerald-800">
            {t("page.processQr.allLabelsIssued")}
          </div>
        ) : (
          <div className="card p-6 text-sm text-[#8a8472] no-print">
            {t("page.processQr.selectOrderHint")}
          </div>
        )}
        </div>
      </section>

      <section ref={issuedLabelsSectionRef} className="mt-5 card p-4 no-print">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="app-card-title">{t("page.processQr.issuedLabels")}</h2>
            <p className="mt-1 text-xs text-[#8a8472]">{t("page.processQr.issuedLabelsHint")}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="btn"
              onClick={() => printIssuedLabels(editedIssuedLabels)}
              disabled={editedIssuedLabels.length === 0 || preparingPrint}
            >
              {preparingPrint ? <RefreshCw className="animate-spin" /> : <Printer />}
              <span>{t("page.processQr.printEdited", { count: editedIssuedLabels.length.toLocaleString() })}</span>
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => printIssuedLabels(orderedIssuedLabels)}
              disabled={activeIssuedLabels.length === 0 || preparingPrint}
            >
              {preparingPrint ? <RefreshCw className="animate-spin" /> : <Printer />}
              <span>{t("page.processQr.printAllIssued")}</span>
            </button>
          </div>
        </div>

        {issuedLabelsLoading ? (
          <div className="py-8 text-center text-sm text-[#8a8472]">{t("common.loading")}</div>
        ) : issuedLabelsBySize.length > 0 ? (
          <div className="space-y-4">
            {issuedLabelsBySize.map(([size, sizeLabels]) => (
              <section key={size} className="overflow-hidden rounded-lg border border-[#ded9ca] bg-white">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#ecebe3] bg-[#f8f6ef] px-4 py-3">
                  <div>
                    <div className="text-sm font-semibold text-[#14110b]">
                      {t("field.size")}: {size}
                    </div>
                    <div className="mt-0.5 text-xs text-[#8a8472]">
                      {t("page.processQr.issuedLabelCount", { count: sizeLabels.length.toLocaleString() })}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      className="btn btn-danger"
                      onClick={() => deleteIssuedSize(size, sizeLabels)}
                      disabled={Boolean(deletingSize) || sizeLabels.some((label) => (
                        label.status !== "available"
                        || Boolean(label.payroll_record_id)
                        || Boolean(label.last_scanned_at)
                        || Number(label.return_count || 0) > 0
                      ))}
                      title={sizeLabels.some((label) => (
                        label.status !== "available"
                        || Boolean(label.payroll_record_id)
                        || Boolean(label.last_scanned_at)
                        || Number(label.return_count || 0) > 0
                      )) ? t("page.processQr.deleteSizeBlocked") : t("page.processQr.deleteSize")}
                    >
                      {deletingSize === size ? <RefreshCw className="animate-spin" /> : <Trash2 />}
                      <span>{t("page.processQr.deleteSize")}</span>
                    </button>
                    <button type="button" className="btn btn-primary" onClick={() => printIssuedLabels(sizeLabels)} disabled={preparingPrint}>
                      {preparingPrint ? <RefreshCw className="animate-spin" /> : <Printer />}
                      <span>{t("page.processQr.printThisSize", { size })}</span>
                    </button>
                  </div>
                </div>
                <div className="label-grid p-3">
                  {sizeLabels.map((label) => (
                    <IssuedProcessLabel
                      key={label.id}
                      label={label}
                      operationNumber={operationNumberForLabel(label, issuedOperationNumbers)}
                      onEdit={() => openLabelCorrection(label)}
                      editable={canCorrectIssuedLabel(label)}
                      editDisabledReason={t("page.processQr.editLabelBlocked")}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-[#d8d2c2] p-8 text-center text-sm text-[#8a8472]">
            {t("page.processQr.noIssuedLabels")}
          </div>
        )}
      </section>

      <Modal
        open={Boolean(labelCorrection)}
        onClose={() => { if (!savingLabelCorrection) setLabelCorrection(null); }}
        title={t("page.processQr.editLabelTitle")}
        closeOnOutsideClick={!savingLabelCorrection}
      >
        {labelCorrection && (
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void saveLabelCorrection();
            }}
          >
            <div className="rounded-md border border-[#ded9ca] bg-[#f8f6ef] px-3 py-2 text-sm text-[#4f493d]">
              <div className="font-semibold text-[#14110b]">QR {labelCorrection.label.qr_token}</div>
              <div className="mt-0.5 text-xs">
                {t("field.size")}: {labelCorrection.label.size || "-"} · {t("field.qty")}: {Number(labelCorrection.label.quantity).toLocaleString()}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                className={`btn justify-center ${labelCorrection.mode === "edit" ? "btn-primary" : ""}`}
                onClick={() => setLabelCorrectionMode("edit")}
              >
                {t("page.processQr.editOnly")}
              </button>
              <button
                type="button"
                className={`btn justify-center ${labelCorrection.mode === "split" ? "btn-primary" : ""}`}
                onClick={() => setLabelCorrectionMode("split")}
              >
                {t("page.processQr.splitQr")}
              </button>
            </div>

            <label className="block">
              <span className="label">{t("page.processQr.operationName")}</span>
              <input
                className="input mt-1 w-full"
                value={labelCorrection.operationName}
                maxLength={255}
                onChange={(event) => setLabelCorrection((current) => current ? {
                  ...current,
                  operationName: event.target.value,
                } : current)}
                autoFocus
              />
            </label>

            <label className="block">
              <span className="label">{t("page.processQr.ratePerPiece")}</span>
              <input
                className="input mt-1 w-full"
                type="number"
                min="0"
                step="0.01"
                value={labelCorrection.ratePerPiece}
                onChange={(event) => setLabelCorrection((current) => current ? {
                  ...current,
                  ratePerPiece: event.target.value,
                } : current)}
              />
            </label>

            {labelCorrection.mode === "split" && (
              <div className="space-y-3 border-t border-[#ded9ca] pt-4">
                <div>
                  <div className="text-sm font-semibold text-[#14110b]">{t("page.processQr.splitQuantities")}</div>
                  <p className="mt-1 text-xs text-[#746d5d]">
                    {t("page.processQr.splitHint", { quantity: Number(labelCorrection.label.quantity).toLocaleString() })}
                  </p>
                </div>
                <div className="space-y-2">
                  {labelCorrection.quantities.map((quantity, index) => (
                    <div key={index} className="flex items-center gap-2">
                      <label className="min-w-0 flex-1">
                        <span className="sr-only">{t("page.processQr.splitPart", { number: index + 1 })}</span>
                        <input
                          className="input w-full"
                          type="number"
                          min="1"
                          step="1"
                          value={quantity}
                          placeholder={t("page.processQr.splitPart", { number: index + 1 })}
                          onChange={(event) => updateSplitQuantity(index, event.target.value)}
                        />
                      </label>
                      <button
                        type="button"
                        className="icon-btn"
                        onClick={() => removeSplitPart(index)}
                        disabled={labelCorrection.quantities.length <= 2}
                        title={t("page.processQr.removeSplitPart")}
                        aria-label={t("page.processQr.removeSplitPart")}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
                <button type="button" className="btn" onClick={addSplitPart}>
                  <Plus className="h-4 w-4" />
                  <span>{t("page.processQr.addSplitPart")}</span>
                </button>
                <div className="flex items-center justify-between border-t border-[#ecebe3] pt-2 text-sm">
                  <span>{t("page.processQr.splitTotal")}</span>
                  <strong>
                    {labelCorrection.quantities.reduce((sum, value) => sum + (Number(value) || 0), 0).toLocaleString()}
                    {" / "}
                    {Number(labelCorrection.label.quantity).toLocaleString()}
                  </strong>
                </div>
                <p className="text-xs text-red-700">{t("page.processQr.splitReplacesOldQr")}</p>
              </div>
            )}

            <div className="flex justify-end gap-2 border-t border-[#ded9ca] pt-4">
              <button type="button" className="btn" onClick={() => setLabelCorrection(null)} disabled={savingLabelCorrection}>
                {t("common.cancel")}
              </button>
              <button type="submit" className="btn btn-primary" disabled={savingLabelCorrection}>
                {savingLabelCorrection ? <RefreshCw className="animate-spin" /> : <Save />}
                <span>{t(labelCorrection.mode === "split" ? "page.processQr.saveAndSplit" : "page.processQr.saveLabelEdit")}</span>
              </button>
            </div>
          </form>
        )}
      </Modal>

      <section className="print-sheet work-print-section" aria-hidden={workLabelsToPrint.length === 0}>
        <div className="label-grid">
          {workLabelsToPrint.map(({ label, qrImage, operationNumber }) => (
            <IssuedProcessLabel key={`print-${label.id}`} label={label} qrImage={qrImage} operationNumber={operationNumber} />
          ))}
        </div>
      </section>

      <style jsx global>{`
        .label-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
          gap: 12px;
        }

        .work-print-section {
          display: none;
        }

        .process-qr-collapsible.is-collapsed {
          display: none;
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
          .process-qr-collapsible.is-collapsed {
            display: block !important;
          }
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
            padding: 1.5mm 3mm 1.5mm 1.5mm !important;
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
            height: 21mm !important;
            width: 21mm !important;
            flex: 0 0 21mm !important;
            align-self: center !important;
          }

          .process-label__title {
            display: -webkit-box !important;
            max-width: 100% !important;
            max-height: 6mm !important;
            overflow: hidden !important;
            color: #000 !important;
            font-size: 8.2pt !important;
            font-weight: 700 !important;
            line-height: 1.05 !important;
            white-space: normal !important;
            overflow-wrap: break-word !important;
            -webkit-box-orient: vertical !important;
            -webkit-line-clamp: 2 !important;
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
            color: #000 !important;
            font-size: 6.4pt !important;
            font-weight: 700 !important;
            line-height: 1.05 !important;
          }

          .process-label--work .process-label__details {
            display: grid !important;
            height: 100% !important;
            grid-template-rows: 1fr 1fr 2.25fr 1fr 1fr 1fr !important;
            font-size: 8.4pt !important;
            line-height: 1 !important;
          }

          .process-label--employee .process-label__title {
            max-height: 7.5mm !important;
            font-size: 9.5pt !important;
            font-weight: 700 !important;
            line-height: 1.05 !important;
          }

          .process-label--employee .process-label__details {
            display: grid !important;
            height: 100% !important;
            grid-template-rows: 1fr 2fr 1fr !important;
            font-size: 8pt !important;
            font-weight: 700 !important;
            line-height: 1.05 !important;
          }

          .process-label--employee .process-label__line {
            grid-template-columns: 7.5mm minmax(0, 1fr) !important;
            min-height: 0 !important;
            align-items: center !important;
          }

          .process-label--employee .process-label__value--wrap {
            max-height: 12mm !important;
            line-height: 1.05 !important;
            -webkit-line-clamp: 3 !important;
          }

          .process-label--employee .process-label__footer {
            font-size: 8.5pt !important;
            font-weight: 700 !important;
          }

          .process-label--work .process-label__qr {
            align-self: flex-start !important;
          }

          .process-label__line {
            grid-template-columns: 9mm minmax(0, 1fr) !important;
            min-height: 2.45mm !important;
            gap: 0.7mm !important;
            align-items: baseline !important;
            overflow: hidden !important;
          }

          .process-label--work .process-label__line {
            grid-template-columns: 9.5mm minmax(0, 1fr) !important;
            min-height: 0 !important;
            align-items: center !important;
          }

          .process-label__line > span:first-child {
            min-width: 0 !important;
            overflow: hidden !important;
            white-space: nowrap !important;
            color: #000 !important;
            font-weight: 700 !important;
          }

          .process-label__value {
            min-width: 0 !important;
            max-width: 100% !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: clip !important;
            word-break: normal !important;
            color: #000 !important;
            font-weight: 700 !important;
          }

          .process-label__value--wrap {
            display: -webkit-box !important;
            max-height: 5mm !important;
            white-space: normal !important;
            overflow-wrap: break-word !important;
            -webkit-box-orient: vertical !important;
            -webkit-line-clamp: 2 !important;
          }

          .process-label--work .process-label__value--wrap {
            max-height: 6.6mm !important;
            line-height: 1.05 !important;
          }

          .process-label--work .process-label__identity-value {
            font-size: 6pt !important;
            line-height: 1.05 !important;
          }

          .process-label--work .process-label__sewing-line-value {
            white-space: pre-line !important;
          }

          .process-label__footer {
            min-height: 3mm !important;
            margin-top: 0.4mm !important;
            padding-top: 0.4mm !important;
            overflow: hidden !important;
            color: #000 !important;
            font-size: 6.2pt !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            letter-spacing: 0 !important;
            white-space: nowrap !important;
            border-top: 0 !important;
          }

          .process-label__number {
            min-width: 8mm !important;
            color: #000 !important;
            font-size: 8pt !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            text-align: right !important;
            white-space: nowrap !important;
          }

          .process-label__kroy {
            min-width: 0 !important;
            overflow: hidden !important;
            text-overflow: clip !important;
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
          <LabelLine label="ID" value={employeeNumber(employee)} strong />
          <LabelLine label={t("field.dept")} value={departmentName} wrap />
          <LabelLine label={t("field.role")} value={employee.position || "-"} wrap />
        </div>
        <ProcessQrImage payload={payload} alt={t("page.processQr.employeeQrAlt")} />
      </div>

      <div className="process-label__footer mt-1 flex items-center justify-end gap-2 border-t border-[#e8e3d6] pt-1 text-[9px] font-semibold text-[#6b6251]">
        <span className="shrink-0">{employeeNumber(employee)}</span>
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

function IssuedProcessLabel({
  label,
  qrImage,
  operationNumber,
  onEdit,
  editable = false,
  editDisabledReason,
}: {
  label: IssuedLabelRow;
  qrImage?: string;
  operationNumber: number;
  onEdit?: () => void;
  editable?: boolean;
  editDisabledReason?: string;
}) {
  const { t } = useT();
  const section = (["sewing", "pressing", "packaging"] as const).includes(
    label.operation_section as "sewing" | "pressing" | "packaging",
  )
    ? label.operation_section as SectionCode
    : "sewing";
  const sewingLine = sewingLinePrintText(label.sewing_line_code, label.sewing_line_name);
  return (
    <article className="process-label process-label--work flex flex-col p-3">
      <div className="process-label__header mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="process-label__title break-words text-[13px] font-bold leading-tight text-[#111]">
            {label.operation_name || label.operation_code || "-"}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {onEdit && (
            <button
              type="button"
              className="icon-btn no-print h-7 w-7"
              onClick={onEdit}
              disabled={!editable}
              title={editable ? t("page.processQr.editLabel") : editDisabledReason}
              aria-label={t("page.processQr.editLabel")}
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
          )}
          <span className="process-label__number font-bold text-[#14110b]">№ {operationNumber}</span>
          <span className={`process-label__badge badge shrink-0 ${SECTION_BADGES[section]}`}>
            {t(`page.processQr.section.${section}`)}
          </span>
        </div>
      </div>

      <div className="process-label__body flex min-h-0 flex-1 gap-2">
        <div className="process-label__details min-w-0 flex-1 text-[10px] leading-tight">
          <LabelLine
            label={t("common.model")}
            value={label.model_code || "-"}
            valueClassName="process-label__identity-value"
          />
          <LabelLine label={t("field.batch")} value={label.batch_no || "-"} />
          <LabelLine
            label={t("page.processQr.line")}
            value={sewingLine}
            strong
            wrap
            valueClassName="process-label__identity-value process-label__sewing-line-value"
          />
          <LabelLine label={t("field.size")} value={label.size || "-"} strong />
          <LabelLine label={t("field.qty")} value={`${Number(label.quantity).toLocaleString()} ${t("field.unitPcs")}`} strong />
          <LabelLine
            label={t("page.processQr.rate")}
            value={Number(label.rate_per_piece) ? `${Number(label.rate_per_piece).toLocaleString()} ${label.currency}` : "-"}
          />
        </div>
        {qrImage ? (
          <img className="process-label__qr" src={qrImage} alt={t("page.processQr.workQrAlt")} />
        ) : (
          <ProcessQrImage payload={label.qr_token} alt={t("page.processQr.workQrAlt")} />
        )}
      </div>

      <div className="process-label__footer mt-1 flex items-center justify-between gap-2 pt-1 text-[9px] font-bold text-[#14110b]">
        <span className="process-label__kroy">
          {t("page.processQr.kroyNo")} {label.cutting_passport_no || "-"}
        </span>
        <span className="shrink-0 font-mono">QR {label.qr_token}</span>
      </div>
    </article>
  );
}

function LabelLine({
  label,
  value,
  strong = false,
  wrap = false,
  valueClassName = "",
}: {
  label: string;
  value: string;
  strong?: boolean;
  wrap?: boolean;
  valueClassName?: string;
}) {
  return (
    <div className="process-label__line grid grid-cols-[33px_minmax(0,1fr)] gap-1">
      <span className="text-[#7a725f]">{label}</span>
      <span className={`process-label__value ${wrap ? "process-label__value--wrap" : ""} ${strong ? "font-bold" : "font-medium"} ${valueClassName}`}>{value}</span>
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
    qrDataUrl(payload)
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
