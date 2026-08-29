"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Ban,
  CheckCircle2,
  CreditCard,
  Lock,
  Plus,
  RefreshCw,
  Save,
  Undo2,
  Unlock,
} from "lucide-react";

import PageHeader from "@/components/PageHeader";
import SearchableSelect from "@/components/SearchableSelect";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useDialogs } from "@/components/DialogProvider";
import { useT } from "@/lib/i18n";

type PayrollPeriod = {
  id: number;
  period_no: string;
  name: string;
  start_date: string;
  end_date: string;
  status: string;
  approved_at?: string | null;
  notes?: string | null;
};

type PayrollRecord = {
  id: number;
  payroll_period_id?: number | null;
  employee_id: number;
  employee_name?: string | null;
  department_name?: string | null;
  production_no?: string | null;
  sales_order_no?: string | null;
  batch_no?: string | null;
  model_code?: string | null;
  operation_section?: string | null;
  operation_code?: string | null;
  operation_name?: string | null;
  quantity: number | string;
  rate_per_piece: number | string;
  currency: string;
  total_amount: number | string;
  scanned_at: string;
  status: string;
};

type PayrollSummaryOperation = {
  employee_id: number;
  operation_section?: string | null;
  operation_code?: string | null;
  operation_name?: string | null;
  currency: string;
  records_count: number;
  quantity: number | string;
  total_amount: number | string;
};

type PayrollSummaryEmployee = {
  employee_id: number;
  employee_name: string;
  department_name?: string | null;
  currency: string;
  records_count: number;
  adjustment_count?: number;
  quantity: number | string;
  piecework_amount?: number | string;
  adjustment_amount?: number | string;
  bonus_amount?: number | string;
  deduction_amount?: number | string;
  total_amount: number | string;
  operations: PayrollSummaryOperation[];
};

type PayrollSummary = {
  records_count: number;
  adjustment_count?: number;
  quantity: number | string;
  piecework_amount?: number | string;
  adjustment_amount?: number | string;
  bonus_amount?: number | string;
  deduction_amount?: number | string;
  total_amount: number | string;
  currency: string;
  employees: PayrollSummaryEmployee[];
};

type PayrollAdjustment = {
  id: number;
  payroll_period_id?: number | null;
  source_payroll_record_id?: number | null;
  employee_id: number;
  adjustment_type: "bonus" | "deduction";
  amount: number | string;
  signed_amount: number | string;
  currency: string;
  reason: string;
  created_at: string;
};

type Employee = {
  id: number;
  full_name: string;
  employee_no?: string | null;
  position?: string | null;
  department_id?: number | null;
  status: string;
};

type Department = {
  id: number;
  name: string;
  code?: string | null;
};

function dateInput(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function monthStart(): string {
  const now = new Date();
  return dateInput(new Date(now.getFullYear(), now.getMonth(), 1));
}

function monthEnd(): string {
  const now = new Date();
  return dateInput(new Date(now.getFullYear(), now.getMonth() + 1, 0));
}

function toStartIso(value: string): string {
  return new Date(`${value}T00:00:00`).toISOString();
}

function toEndIso(value: string): string {
  return new Date(`${value}T23:59:59`).toISOString();
}

function n(value: number | string | null | undefined): number {
  const next = Number(value || 0);
  return Number.isFinite(next) ? next : 0;
}

function money(value: number | string, currency = "UZS"): string {
  return `${n(value).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`;
}

function statusBadge(status: string): string {
  if (status === "paid" || status === "approved") return "badge-green";
  if (status === "locked") return "badge-yellow";
  if (status === "voided" || status === "cancelled") return "badge-red";
  return "";
}

function adjustmentBadge(type: string): string {
  return type === "deduction" ? "badge-red" : "badge-green";
}

const FINALIZED_PERIOD_STATUSES = new Set(["locked", "approved", "paid", "cancelled"]);

function buildPayrollQuery(filters: {
  periodId: string;
  employeeId: string;
  departmentId: string;
  from: string;
  to: string;
}, includeLimit = false): string {
  const params = new URLSearchParams();
  if (filters.periodId) params.set("period_id", filters.periodId);
  if (filters.employeeId) params.set("employee_id", filters.employeeId);
  if (filters.departmentId) params.set("department_id", filters.departmentId);
  if (filters.from) params.set("date_from", toStartIso(filters.from));
  if (filters.to) params.set("date_to", toEndIso(filters.to));
  if (includeLimit) params.set("limit", "300");
  return params.toString();
}

export default function PayrollPage() {
  const dialogs = useDialogs();
  const { t, lang } = useT();
  const { me } = useMe();
  const canManage = can(me, "payroll.manage", "*");
  const canApprove = can(me, "payroll.approve", "*");
  const canPay = can(me, "payroll.pay", "*");
  const [filters, setFilters] = useState({ periodId: "", employeeId: "", departmentId: "", from: "", to: "" });
  const [periodForm, setPeriodForm] = useState({
    name: `Payroll ${monthStart().slice(0, 7)}`,
    start_date: monthStart(),
    end_date: monthEnd(),
    status: "open",
    notes: "",
  });
  const [adjustmentForm, setAdjustmentForm] = useState({
    payroll_period_id: "",
    employee_id: "",
    adjustment_type: "bonus",
    amount: "",
    reason: "",
  });
  const [reversalForm, setReversalForm] = useState<{
    record: PayrollRecord | null;
    target_period_id: string;
    reason: string;
  }>({ record: null, target_period_id: "", reason: "" });
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<"success" | "error" | "info">("info");

  const { data: periods = [], mutate: mutatePeriods } = useSWR<PayrollPeriod[]>("/api/payroll/periods", fetcher);
  const { data: employees = [] } = useSWR<Employee[]>("/api/employees", fetcher);
  const { data: departments = [] } = useSWR<Department[]>("/api/departments", fetcher);

  const recordsQuery = [buildPayrollQuery(filters, true), "status=active"].filter(Boolean).join("&");
  const summaryQuery = buildPayrollQuery(filters);
  const { data: records = [], mutate: mutateRecords } = useSWR<PayrollRecord[]>(
    `/api/payroll/records?${recordsQuery}`,
    fetcher,
  );
  const { data: summary, mutate: mutateSummary } = useSWR<PayrollSummary>(
    `/api/payroll/summary${summaryQuery ? `?${summaryQuery}` : ""}`,
    fetcher,
  );
  const { data: adjustments = [], mutate: mutateAdjustments } = useSWR<PayrollAdjustment[]>(
    `/api/payroll/adjustments${summaryQuery ? `?${summaryQuery}` : ""}`,
    fetcher,
  );

  const periodById = useMemo(() => new Map(periods.map((period) => [Number(period.id), period])), [periods]);
  const employeeById = useMemo(() => new Map(employees.map((employee) => [Number(employee.id), employee])), [employees]);
  const departmentById = useMemo(() => new Map(departments.map((department) => [Number(department.id), department])), [departments]);
  const employeeFilterOptions = useMemo(() => [
    { value: "", label: t("page.payroll.allEmployees") },
    ...employees.map((employee) => {
      const department = employee.department_id ? departmentById.get(Number(employee.department_id)) : null;
      return {
        value: String(employee.id),
        label: employee.full_name,
        searchText: [
          employee.employee_no,
          employee.id,
          employee.position,
          department?.code,
          department?.name,
        ].filter(Boolean).join(" "),
      };
    }),
  ], [departmentById, employees, t]);
  const adjustmentPeriod = adjustmentForm.payroll_period_id ? periodById.get(Number(adjustmentForm.payroll_period_id)) : null;
  const adjustmentPeriodFinalized = Boolean(adjustmentPeriod && FINALIZED_PERIOD_STATUSES.has(adjustmentPeriod.status));
  const operationRows = useMemo(() => (
    (summary?.employees || []).flatMap((employee) => (
      (employee.operations || []).map((operation) => ({
        ...operation,
        employee_name: employee.employee_name,
        department_name: employee.department_name,
      }))
    ))
  ), [summary?.employees]);

  function notice(text: string, tone: typeof messageTone = "info") {
    setMessage(text);
    setMessageTone(tone);
  }

  async function refreshAll() {
    await Promise.all([mutatePeriods(), mutateRecords(), mutateSummary(), mutateAdjustments()]);
  }

  async function createPeriod(event: React.FormEvent) {
    event.preventDefault();
    if (!canManage) return;
    try {
      await api.post("/api/payroll/periods", {
        name: periodForm.name,
        start_date: toStartIso(periodForm.start_date),
        end_date: toEndIso(periodForm.end_date),
        status: periodForm.status,
        notes: periodForm.notes || null,
      });
      notice(t("page.payroll.periodCreated"), "success");
      await refreshAll();
    } catch (error: any) {
      notice(error?.message || t("page.payroll.periodCreateFailed"), "error");
    }
  }

  async function createAdjustment(event: React.FormEvent) {
    event.preventDefault();
    if (!canManage) return;
    const employeeId = Number(adjustmentForm.employee_id || 0);
    const amount = Math.abs(Number(adjustmentForm.amount || 0));
    if (!employeeId || !Number.isFinite(amount) || amount <= 0) {
      notice(t("page.payroll.invalidAdjustment"), "error");
      return;
    }
    if (adjustmentPeriodFinalized) {
      notice(t("page.payroll.finalizedAdjustment"), "error");
      return;
    }
    try {
      await api.post("/api/payroll/adjustments", {
        payroll_period_id: adjustmentForm.payroll_period_id ? Number(adjustmentForm.payroll_period_id) : null,
        employee_id: employeeId,
        adjustment_type: adjustmentForm.adjustment_type,
        amount,
        reason: adjustmentForm.reason.trim(),
      });
      setAdjustmentForm({ ...adjustmentForm, amount: "", reason: "" });
      notice(t("page.payroll.adjustmentAdded"), "success");
      await refreshAll();
    } catch (error: any) {
      notice(error?.message || t("page.payroll.adjustmentAddFailed"), "error");
    }
  }

  async function patchPeriod(period: PayrollPeriod, patch: Partial<PayrollPeriod>) {
    try {
      await api.patch(`/api/payroll/periods/${period.id}`, patch);
      notice(t("page.payroll.periodUpdated"), "success");
      await refreshAll();
    } catch (error: any) {
      notice(error?.message || t("page.payroll.periodUpdateFailed"), "error");
    }
  }

  async function periodAction(period: PayrollPeriod, action: "lock" | "approve" | "mark-paid") {
    try {
      await api.post(`/api/payroll/periods/${period.id}/${action}`);
      notice(t("page.payroll.periodUpdated"), "success");
      await refreshAll();
    } catch (error: any) {
      notice(error?.message || t("page.payroll.periodUpdateFailed"), "error");
    }
  }

  async function voidRecord(record: PayrollRecord) {
    if (!(await dialogs.ask({ message: t("page.payroll.voidConfirm", { id: record.id }), tone: "danger" }))) return;
    try {
      await api.post(`/api/payroll/records/${record.id}/void`);
      notice(t("page.payroll.recordVoided"), "success");
      await refreshAll();
    } catch (error: any) {
      notice(error?.message || t("page.payroll.recordVoidFailed"), "error");
    }
  }

  function startReversal(record: PayrollRecord) {
    const target = periods.find((period) => (
      !FINALIZED_PERIOD_STATUSES.has(period.status) && Number(period.id) !== Number(record.payroll_period_id)
    ));
    setReversalForm({ record, target_period_id: target ? String(target.id) : "", reason: "" });
  }

  async function createReversal(event: React.FormEvent) {
    event.preventDefault();
    const record = reversalForm.record;
    const targetPeriodId = Number(reversalForm.target_period_id || 0);
    const reason = reversalForm.reason.trim();
    if (!record || !targetPeriodId || reason.length < 3) {
      notice(t("page.payroll.invalidReversal"), "error");
      return;
    }
    try {
      await api.post(`/api/payroll/records/${record.id}/reverse-as-adjustment`, {
        target_period_id: targetPeriodId,
        reason,
      });
      setReversalForm({ record: null, target_period_id: "", reason: "" });
      notice(t("page.payroll.reversalCreated"), "success");
      await refreshAll();
    } catch (error: any) {
      notice(error?.message || t("page.payroll.reversalFailed"), "error");
    }
  }

  const messageClass = {
    info: "border-[#ded9ca] bg-[#f8f6ef] text-[#56503f]",
    success: "border-emerald-200 bg-emerald-50 text-emerald-700",
    error: "border-red-200 bg-red-50 text-red-700",
  }[messageTone];

  return (
    <div>
      <PageHeader
        title={t("page.payroll.title")}
        subtitle={t("page.payroll.subtitle")}
        actions={(
          <button type="button" className="btn" onClick={refreshAll}>
            <RefreshCw />
            <span>{t("page.payroll.refresh")}</span>
          </button>
        )}
      />

      {message && <div className={`mb-4 rounded-md border p-3 text-sm ${messageClass}`}>{message}</div>}

      <div className={`mb-4 grid grid-cols-1 gap-4 ${canManage ? "xl:grid-cols-[minmax(320px,430px)_minmax(0,1fr)]" : ""}`}>
        <form onSubmit={createPeriod} className="card p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="app-card-title">{t("page.payroll.newPeriod")}</h2>
            <Plus className="h-5 w-5 text-[#8a8472]" />
          </div>
          <div className="space-y-3">
            <div>
              <label className="label">{t("common.name")}</label>
              <input className="input" value={periodForm.name} onChange={(event) => setPeriodForm({ ...periodForm, name: event.target.value })} required />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">{t("page.payroll.start")}</label>
                <input className="input" type="date" value={periodForm.start_date} onChange={(event) => setPeriodForm({ ...periodForm, start_date: event.target.value })} required />
              </div>
              <div>
                <label className="label">{t("page.payroll.end")}</label>
                <input className="input" type="date" value={periodForm.end_date} onChange={(event) => setPeriodForm({ ...periodForm, end_date: event.target.value })} required />
              </div>
            </div>
            <div>
              <label className="label">{t("common.status")}</label>
              <select className="input" value={periodForm.status} onChange={(event) => setPeriodForm({ ...periodForm, status: event.target.value })}>
                <option value="open">{t("statusValue.open")}</option>
                <option value="draft">{t("statusValue.draft")}</option>
              </select>
            </div>
            <div>
              <label className="label">{t("common.notes")}</label>
              <textarea className="input min-h-20" value={periodForm.notes} onChange={(event) => setPeriodForm({ ...periodForm, notes: event.target.value })} />
            </div>
            <button className="btn btn-primary w-full" disabled={!canManage}>
              <Save />
              <span>{t("page.payroll.createPeriod")}</span>
            </button>
          </div>
        </form>

        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4">
            <h2 className="app-card-title">{t("page.payroll.periods")}</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="table min-w-[900px]">
              <thead>
                <tr>
                  <th>{t("page.payroll.period")}</th>
                  <th>{t("page.payroll.dates")}</th>
                  <th>{t("common.status")}</th>
                  <th>{t("page.payroll.approved")}</th>
                  <th>{t("common.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {periods.length === 0 && (
                  <tr><td colSpan={5} className="text-sm text-[#8a8472]">{t("page.payroll.noPeriods")}</td></tr>
                )}
                {periods.map((period) => (
                  <tr key={period.id}>
                    <td>
                      <div className="font-medium">{period.name}</div>
                      <div className="text-xs text-[#8a8472]">{period.period_no}</div>
                    </td>
                    <td>{new Date(period.start_date).toLocaleDateString(lang)} - {new Date(period.end_date).toLocaleDateString(lang)}</td>
                    <td><span className={`badge ${statusBadge(period.status)}`}>{t(`statusValue.${period.status}`)}</span></td>
                    <td>{period.approved_at ? new Date(period.approved_at).toLocaleString(lang) : "-"}</td>
                    <td>
                      <div className="flex flex-wrap gap-2">
                        {canManage && period.status !== "open" && period.status !== "paid" && period.status !== "cancelled" && (
                          <button type="button" className="btn h-8 px-2 text-[11px]" onClick={() => patchPeriod(period, { status: "open" })}>
                            <Unlock />
                            <span>{t("statusValue.open")}</span>
                          </button>
                        )}
                        {canManage && !["locked", "approved", "paid", "cancelled"].includes(period.status) && (
                          <button type="button" className="btn h-8 px-2 text-[11px]" onClick={() => periodAction(period, "lock")}>
                            <Lock />
                            <span>{t("page.payroll.lock")}</span>
                          </button>
                        )}
                        {canApprove && !["approved", "paid", "cancelled"].includes(period.status) && (
                          <button type="button" className="btn h-8 px-2 text-[11px]" onClick={() => periodAction(period, "approve")}>
                            <CheckCircle2 />
                            <span>{t("page.payroll.approve")}</span>
                          </button>
                        )}
                        {canPay && period.status === "approved" && (
                          <button type="button" className="btn h-8 px-2 text-[11px]" onClick={() => periodAction(period, "mark-paid")}>
                            <CreditCard />
                            <span>{t("page.payroll.paid")}</span>
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="card mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1">
            <label className="label">{t("page.payroll.period")}</label>
            <select className="input" value={filters.periodId} onChange={(event) => setFilters({ ...filters, periodId: event.target.value })}>
              <option value="">{t("page.payroll.allPeriods")}</option>
              {periods.map((period) => (
                <option key={period.id} value={period.id}>{period.period_no} - {period.name}</option>
              ))}
            </select>
          </div>
          <div className="min-w-[220px] flex-1">
            <label className="label" htmlFor="payroll-summary-employee">{t("page.payroll.employee")}</label>
            <SearchableSelect<string>
              inputId="payroll-summary-employee"
              value={filters.employeeId}
              options={employeeFilterOptions}
              placeholder={t("page.payroll.searchEmployee")}
              noResultsText={t("page.payroll.noEmployeeResults")}
              onChange={(employeeId) => setFilters((current) => ({ ...current, employeeId }))}
            />
          </div>
          <div className="min-w-[200px] flex-1">
            <label className="label">{t("field.department")}</label>
            <select className="input" value={filters.departmentId} onChange={(event) => setFilters({ ...filters, departmentId: event.target.value })}>
              <option value="">{t("page.payroll.allDepartments")}</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>{department.code ? `${department.code} - ` : ""}{department.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">{t("field.from")}</label>
            <input className="input" type="date" value={filters.from} onChange={(event) => setFilters({ ...filters, from: event.target.value })} />
          </div>
          <div>
            <label className="label">{t("field.to")}</label>
            <input className="input" type="date" value={filters.to} onChange={(event) => setFilters({ ...filters, to: event.target.value })} />
          </div>
        </div>
      </section>

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <div className="kpi-card">
          <div className="label">{t("page.payroll.records")}</div>
          <div className="text-2xl font-semibold">{Number(summary?.records_count || 0).toLocaleString()}</div>
        </div>
        <div className="kpi-card">
          <div className="label">{t("page.payroll.pieces")}</div>
          <div className="text-2xl font-semibold">{n(summary?.quantity).toLocaleString()}</div>
        </div>
        <div className="kpi-card">
          <div className="label">{t("page.payroll.piecework")}</div>
          <div className="text-2xl font-semibold">{money(summary?.piecework_amount || 0, summary?.currency || "UZS")}</div>
        </div>
        <div className="kpi-card">
          <div className="label">{t("page.payroll.adjustments")}</div>
          <div className="text-2xl font-semibold">{money(summary?.adjustment_amount || 0, summary?.currency || "UZS")}</div>
          <div className="mt-1 text-xs text-[#8a8472]">
            +{money(summary?.bonus_amount || 0, summary?.currency || "UZS")} / -{money(summary?.deduction_amount || 0, summary?.currency || "UZS")}
          </div>
        </div>
        <div className="kpi-card">
          <div className="label">{t("page.payroll.netPayroll")}</div>
          <div className="text-2xl font-semibold">{money(summary?.total_amount || 0, summary?.currency || "UZS")}</div>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(320px,430px)_minmax(0,1fr)]">
        {canManage && (
          <form onSubmit={createAdjustment} className="card p-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="app-card-title">{t("page.payroll.newAdjustment")}</h2>
              <Plus className="h-5 w-5 text-[#8a8472]" />
            </div>
            <div className="space-y-3">
              <div>
                <label className="label">{t("page.payroll.period")}</label>
                <select
                  className="input"
                  value={adjustmentForm.payroll_period_id}
                  onChange={(event) => setAdjustmentForm({ ...adjustmentForm, payroll_period_id: event.target.value })}
                >
                  <option value="">{t("page.payroll.noPeriod")}</option>
                  {periods.map((period) => (
                    <option key={period.id} value={period.id}>{period.period_no} - {period.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">{t("page.payroll.employee")}</label>
                <select
                  className="input"
                  value={adjustmentForm.employee_id}
                  onChange={(event) => setAdjustmentForm({ ...adjustmentForm, employee_id: event.target.value })}
                  required
                >
                  <option value="">{t("page.payroll.selectEmployee")}</option>
                  {employees.map((employee) => (
                    <option key={employee.id} value={employee.id}>{employee.full_name}</option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="label">{t("field.type")}</label>
                  <select
                    className="input"
                    value={adjustmentForm.adjustment_type}
                    onChange={(event) => setAdjustmentForm({ ...adjustmentForm, adjustment_type: event.target.value })}
                  >
                    <option value="bonus">{t("page.payroll.bonus")}</option>
                    <option value="deduction">{t("page.payroll.deduction")}</option>
                  </select>
                </div>
                <div>
                  <label className="label">{t("field.amount")}</label>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    step="0.01"
                    value={adjustmentForm.amount}
                    onChange={(event) => setAdjustmentForm({ ...adjustmentForm, amount: event.target.value })}
                    required
                  />
                </div>
              </div>
              <div>
                <label className="label">{t("field.reason")}</label>
                <input className="input" value={adjustmentForm.reason} onChange={(event) => setAdjustmentForm({ ...adjustmentForm, reason: event.target.value })} required />
              </div>
              {adjustmentPeriodFinalized && (
                <div className="text-sm text-red-700">{t("page.payroll.adjustmentsClosed", { status: t(`statusValue.${adjustmentPeriod?.status}`) })}</div>
              )}
              <button className="btn btn-primary w-full" disabled={adjustmentPeriodFinalized}>
                <Save />
                <span>{t("page.payroll.addAdjustment")}</span>
              </button>
            </div>
          </form>
        )}

        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4">
            <h2 className="app-card-title">{t("page.payroll.adjustments")}</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="table min-w-[840px]">
              <thead>
                <tr>
                  <th>{t("common.created")}</th>
                  <th>{t("page.payroll.employee")}</th>
                  <th>{t("page.payroll.period")}</th>
                  <th>{t("field.type")}</th>
                  <th>{t("field.amount")}</th>
                  <th>{t("field.reason")}</th>
                </tr>
              </thead>
              <tbody>
                {adjustments.length === 0 && (
                  <tr><td colSpan={6} className="text-sm text-[#8a8472]">{t("page.payroll.noAdjustments")}</td></tr>
                )}
                {adjustments.map((adjustment) => {
                  const employee = employeeById.get(Number(adjustment.employee_id));
                  const period = adjustment.payroll_period_id ? periodById.get(Number(adjustment.payroll_period_id)) : null;
                  return (
                    <tr key={adjustment.id}>
                      <td>{new Date(adjustment.created_at).toLocaleString(lang)}</td>
                      <td>{employee?.full_name || t("page.payroll.employeeId", { id: adjustment.employee_id })}</td>
                      <td>{period?.period_no || "-"}</td>
                      <td><span className={`badge ${adjustmentBadge(adjustment.adjustment_type)}`}>{t(`page.payroll.${adjustment.adjustment_type}`)}</span></td>
                      <td className="font-semibold">{money(adjustment.signed_amount, adjustment.currency)}</td>
                      <td>
                        <div>{adjustment.reason}</div>
                        {adjustment.source_payroll_record_id && (
                          <div className="mt-1 text-xs text-[#8a8472]">
                            {t("page.payroll.reversalOfRecord", { id: adjustment.source_payroll_record_id })}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4">
            <h2 className="app-card-title">{t("page.payroll.employeeTotals")}</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="table min-w-[760px]">
              <thead>
                <tr>
                  <th>{t("page.payroll.employee")}</th>
                  <th>{t("field.department")}</th>
                  <th>{t("page.payroll.records")}</th>
                  <th>{t("page.payroll.pieces")}</th>
                  <th>{t("page.payroll.piecework")}</th>
                  <th>{t("page.payroll.adjustments")}</th>
                  <th>{t("page.payroll.netTotal")}</th>
                </tr>
              </thead>
              <tbody>
                {(summary?.employees || []).length === 0 && (
                  <tr><td colSpan={7} className="text-sm text-[#8a8472]">{t("page.payroll.noTotals")}</td></tr>
                )}
                {(summary?.employees || []).map((row) => (
                  <tr key={`${row.employee_id}-${row.currency}`}>
                    <td>{row.employee_name}</td>
                    <td>{row.department_name || "-"}</td>
                    <td>{Number(row.records_count || 0).toLocaleString()}</td>
                    <td>{n(row.quantity).toLocaleString()}</td>
                    <td className="font-semibold">{money(row.piecework_amount || 0, row.currency)}</td>
                    <td className="font-semibold">{money(row.adjustment_amount || 0, row.currency)}</td>
                    <td className="font-semibold">{money(row.total_amount, row.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4">
            <h2 className="app-card-title">{t("page.payroll.operationTotals")}</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="table min-w-[840px]">
              <thead>
                <tr>
                  <th>{t("page.payroll.employee")}</th>
                  <th>{t("field.operation")}</th>
                  <th>{t("page.payroll.records")}</th>
                  <th>{t("page.payroll.pieces")}</th>
                  <th>{t("common.total")}</th>
                </tr>
              </thead>
              <tbody>
                {operationRows.length === 0 && (
                  <tr><td colSpan={5} className="text-sm text-[#8a8472]">{t("page.payroll.noOperationTotals")}</td></tr>
                )}
                {operationRows.map((row, index) => (
                  <tr key={`${row.employee_id}-${row.operation_code || index}-${row.currency}`}>
                    <td>
                      <div>{row.employee_name}</div>
                      <div className="text-xs text-[#8a8472]">{row.department_name || "-"}</div>
                    </td>
                    <td>
                      <div className="font-medium">{row.operation_name || row.operation_code || "-"}</div>
                      <div className="text-xs text-[#8a8472]">{row.operation_section || "-"} - {row.operation_code || "-"}</div>
                    </td>
                    <td>{Number(row.records_count || 0).toLocaleString()}</td>
                    <td>{n(row.quantity).toLocaleString()}</td>
                    <td className="font-semibold">{money(row.total_amount, row.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="card overflow-hidden">
        <div className="border-b border-[#ecebe3] p-4">
          <h2 className="app-card-title">{t("page.payroll.payrollRecords")}</h2>
        </div>
        {reversalForm.record && (
          <form onSubmit={createReversal} className="border-b border-[#ecebe3] bg-[#faf9f5] p-4">
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-[#28251d]">{t("page.payroll.reversalTitle")}</h3>
                <p className="mt-1 text-xs text-[#746e5d]">
                  {t("page.payroll.reversalSource", {
                    id: reversalForm.record.id,
                    employee: reversalForm.record.employee_name || t("page.payroll.employeeId", { id: reversalForm.record.employee_id }),
                    amount: money(reversalForm.record.total_amount, reversalForm.record.currency),
                  })}
                </p>
              </div>
              <button
                type="button"
                className="btn h-8 px-3 text-xs"
                onClick={() => setReversalForm({ record: null, target_period_id: "", reason: "" })}
              >
                {t("common.cancel")}
              </button>
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(220px,320px)_minmax(280px,1fr)_auto] md:items-end">
              <div>
                <label className="label">{t("page.payroll.targetPeriod")}</label>
                <select
                  className="select"
                  value={reversalForm.target_period_id}
                  onChange={(event) => setReversalForm({ ...reversalForm, target_period_id: event.target.value })}
                  required
                >
                  <option value="">{t("page.payroll.selectEditablePeriod")}</option>
                  {periods.filter((period) => (
                    !FINALIZED_PERIOD_STATUSES.has(period.status)
                    && Number(period.id) !== Number(reversalForm.record?.payroll_period_id)
                  )).map((period) => (
                    <option key={period.id} value={period.id}>{period.period_no} — {period.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">{t("page.payroll.reversalReason")}</label>
                <input
                  className="input"
                  value={reversalForm.reason}
                  onChange={(event) => setReversalForm({ ...reversalForm, reason: event.target.value })}
                  placeholder={t("page.payroll.reversalReasonPlaceholder")}
                  minLength={3}
                  maxLength={255}
                  required
                />
              </div>
              <button type="submit" className="btn btn-primary" disabled={!reversalForm.target_period_id || reversalForm.reason.trim().length < 3}>
                <Undo2 />
                <span>{t("page.payroll.postReversal")}</span>
              </button>
            </div>
            {periods.every((period) => FINALIZED_PERIOD_STATUSES.has(period.status) || Number(period.id) === Number(reversalForm.record?.payroll_period_id)) && (
              <p className="mt-3 text-xs text-amber-700">{t("page.payroll.noEditablePeriod")}</p>
            )}
          </form>
        )}
        <div className="overflow-x-auto">
          <table className="table min-w-[1280px]">
            <thead>
              <tr>
                <th>{t("page.payroll.time")}</th>
                <th>{t("page.payroll.employee")}</th>
                <th>{t("page.payroll.period")}</th>
                <th>{t("field.production")}</th>
                <th>{t("field.batch")}</th>
                <th>{t("field.operation")}</th>
                <th>{t("field.qty")}</th>
                <th>{t("page.payroll.rate")}</th>
                <th>{t("common.total")}</th>
                <th>{t("common.status")}</th>
                <th>{t("common.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {records.length === 0 && (
                <tr><td colSpan={11} className="text-sm text-[#8a8472]">{t("page.payroll.noRecords")}</td></tr>
              )}
              {records.map((record) => {
                const period = record.payroll_period_id ? periodById.get(Number(record.payroll_period_id)) : null;
                const sourceFinalized = record.status === "approved" || record.status === "paid" || Boolean(
                  period && ["locked", "approved", "paid"].includes(period.status)
                );
                const canVoidRecord = record.status !== "voided" && !sourceFinalized && !Boolean(
                  period && FINALIZED_PERIOD_STATUSES.has(period.status)
                );
                const employeeDept = record.department_name || (
                  employees.find((employee) => Number(employee.id) === Number(record.employee_id))?.department_id
                    ? departmentById.get(Number(employees.find((employee) => Number(employee.id) === Number(record.employee_id))?.department_id))?.name
                    : null
                );
                return (
                  <tr key={record.id}>
                    <td>{new Date(record.scanned_at).toLocaleString(lang)}</td>
                    <td>
                      <div className="font-medium">{record.employee_name || t("page.payroll.employeeId", { id: record.employee_id })}</div>
                      <div className="text-xs text-[#8a8472]">{employeeDept || "-"}</div>
                    </td>
                    <td>{period ? period.period_no : "-"}</td>
                    <td>
                      <div>{record.production_no || "-"}</div>
                      <div className="text-xs text-[#8a8472]">{record.sales_order_no || "-"}</div>
                    </td>
                    <td>{record.batch_no || "-"}</td>
                    <td>
                      <div className="font-medium">{record.operation_name || record.operation_code || "-"}</div>
                      <div className="text-xs text-[#8a8472]">{record.operation_section || "-"} - {record.operation_code || "-"}</div>
                    </td>
                    <td>{n(record.quantity).toLocaleString()}</td>
                    <td>{money(record.rate_per_piece, record.currency)}</td>
                    <td className="font-semibold">{money(record.total_amount, record.currency)}</td>
                    <td><span className={`badge ${statusBadge(record.status)}`}>{t(`statusValue.${record.status}`)}</span></td>
                    <td>
                      {canManage && canVoidRecord ? (
                        <button type="button" className="btn h-8 px-2 text-[11px]" onClick={() => voidRecord(record)}>
                          <Ban />
                          <span>{t("page.payroll.void")}</span>
                        </button>
                      ) : canManage && sourceFinalized ? (
                        <button type="button" className="btn h-8 px-2 text-[11px]" onClick={() => startReversal(record)}>
                          <Undo2 />
                          <span>{t("page.payroll.reverseAsAdjustment")}</span>
                        </button>
                      ) : "-"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
