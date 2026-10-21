"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher, fetchResponse } from "@/lib/api";
import Modal from "@/components/Modal";
import { HrHeader, LoadState, MetricGrid } from "@/components/hr/HrUi";
import { useT } from "@/lib/i18n";

type Dept = { id: number; name: string };
type Position = { id: number; name: string };
type Employee = {
  id: number; factory_code: string; employee_no: string | null; full_name: string;
  department_id: number | null; position: string | null; phone: string | null;
  salary: number | null; status: string; joined_at: string | null;
  manager_employee_id: number | null; manager_name?: string | null; hr_position_id: number | null; position_name?: string | null; hr_profile_json: Record<string, unknown>;
};
type EmployeePage = { rows: Employee[]; total: number; page: number; page_size: number; has_more: boolean; active_total: number; inactive_total: number; profile_coverage_percent: number | null; search: string };
type ManagerOptions = { rows: { id: number; full_name: string }[]; has_more: boolean };
type FormState = {
  employee_no: string; full_name: string; department_id: string; position: string; phone: string;
  salary: string; status: string; joined_at: string; manager_employee_id: string; hr_position_id: string;
  profile: Record<string, string>;
};

const PROFILE_FIELDS = {
  Personal: [
    ["photo_url", "page.hrEmployees.photo_url", "url"], ["date_of_birth", "page.hrEmployees.date_of_birth", "date"],
    ["gender", "page.hrEmployees.gender", "text"], ["email", "page.hrEmployees.email", "email"], ["address", "page.hrEmployees.address", "text"],
    ["emergency_contact", "page.hrEmployees.emergency_contact", "text"], ["nationality", "page.hrEmployees.nationality", "text"],
  ],
  Employment: [
    ["company", "page.hrEmployees.company", "text"], ["branch", "page.hrEmployees.branch", "text"], ["section", "page.hrEmployees.section", "text"],
    ["grade_level", "page.hrEmployees.grade_level", "text"], ["employment_type", "page.hrEmployees.employment_type", "text"],
    ["probation_end", "page.hrEmployees.probation_end", "date"], ["work_schedule", "page.hrEmployees.work_schedule", "text"],
    ["shift", "page.hrEmployees.shift", "text"], ["workplace", "page.hrEmployees.workplace", "text"],
    ["scheduled_daily_hours", "page.hrEmployees.scheduled_daily_hours", "number"],
  ],
  Financial: [
    ["rate_type", "page.hrEmployees.rate_type", "text"], ["bonus_scheme", "page.hrEmployees.bonus_scheme", "text"],
    ["bank_details", "page.hrEmployees.bank_details", "text"], ["payroll_id", "page.hrEmployees.payroll_id", "text"],
  ],
} as const;

const EMPTY: FormState = { employee_no: "", full_name: "", department_id: "", position: "", phone: "", salary: "", status: "active", joined_at: "", manager_employee_id: "", hr_position_id: "", profile: {} };

function effectiveEmployeeNumber(employee: Pick<Employee, "id" | "employee_no">): string {
  const configured = String(employee.employee_no || "").trim();
  return configured || String(employee.id).padStart(4, "0");
}

function toForm(employee?: Employee | null): FormState {
  if (!employee) return structuredClone(EMPTY);
  const profile: Record<string, string> = {};
  Object.entries(employee.hr_profile_json || {}).forEach(([key, value]) => { profile[key] = value == null ? "" : String(value); });
  return { employee_no: employee.employee_no || "", full_name: employee.full_name, department_id: employee.department_id ? String(employee.department_id) : "", position: employee.position || "", phone: employee.phone || "", salary: employee.salary == null ? "" : String(employee.salary), status: employee.status, joined_at: employee.joined_at ? employee.joined_at.slice(0, 10) : "", manager_employee_id: employee.manager_employee_id ? String(employee.manager_employee_id) : "", hr_position_id: employee.hr_position_id ? String(employee.hr_position_id) : "", profile };
}

export default function EmployeesPage() {
  const { t, lang } = useT();
  function employeeStatusLabel(status: string) {
    return ["active", "inactive", "on_leave", "terminated"].includes(status)
      ? t(`page.hrEmployees.${status}`) : status.replaceAll("_", " ");
  }
  const PAGE_SIZE = 50;
  const [page, setPage] = useState(1);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [query, setQuery] = useState("");
  const { data, error, isLoading, mutate } = useSWR<EmployeePage>(`/api/employees?page=${page}&page_size=${PAGE_SIZE}&search=${encodeURIComponent(query)}`, fetcher);
  const { data: departments } = useSWR<Dept[]>("/api/departments", fetcher);
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [positionSearch, setPositionSearch] = useState("");
  const positionDirectoryKey = editing !== null
    ? `/api/employees/position-options?search=${encodeURIComponent(positionSearch)}${form.hr_position_id ? `&selected_id=${form.hr_position_id}` : ""}`
    : null;
  const { data: positionOptions } = useSWR<{ rows: Position[]; has_more: boolean }>(positionDirectoryKey, fetcher);
  const positions = positionOptions?.rows;
  const [managerSearch, setManagerSearch] = useState("");
  const managerSelected = form.manager_employee_id ? Number(form.manager_employee_id) : null;
  const managerKey = editing !== null
    ? `/api/employees/manager-options?search=${encodeURIComponent(managerSearch)}${managerSelected ? `&selected_id=${managerSelected}` : ""}`
    : null;
  const { data: managerOptions } = useSWR<ManagerOptions>(managerKey, fetcher);
  const [section, setSection] = useState<keyof typeof PROFILE_FIELDS>("Personal");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  async function downloadEmployees() {
    if (exporting) return;
    setExporting(true); setExportError("");
    try {
      const response = await fetchResponse(`/api/employees/export.xlsx?search=${encodeURIComponent(query)}&lang=${lang}`, { credentials: "include" });
      if (!response.ok) throw new Error("Employee export failed");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = "employees.xlsx";
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch { setExportError(t("employeeExport.error")); }
    finally { setExporting(false); }
  }

  useEffect(() => {
    if (!data || data.page !== page || data.search !== query.trim()) return;
    setEmployees((current) => page === 1
      ? data.rows
      : Array.from(new Map([...current, ...data.rows].map((row) => [row.id, row])).values()));
  }, [data, page, query]);
  const activePageData = data?.page === page && data.search === query.trim() ? data : undefined;
  const filtered = useMemo(() => employees, [employees]);
  function changeQuery(value: string) { setEmployees([]); setPage(1); setQuery(value); }

  function open(employee?: Employee) { setEditing(employee || "new"); setForm(toForm(employee)); setManagerSearch(""); setPositionSearch(""); setSection("Personal"); setMessage(""); }
  function profileValue(key: string) { return form.profile[key] || ""; }
  function setProfile(key: string, value: string) { setForm((old) => ({ ...old, profile: { ...old.profile, [key]: value } })); }

  async function save(event: React.FormEvent) {
    event.preventDefault(); setSaving(true); setMessage("");
    const edit = form;
    const payload = {
      employee_no: edit.employee_no.trim() || null, full_name: form.full_name.trim(),
      department_id: form.department_id ? Number(form.department_id) : null,
      position: form.position.trim() || null, phone: form.phone.trim() || null,
      salary: form.salary === "" ? null : Number(form.salary), status: form.status,
      joined_at: form.joined_at ? new Date(`${form.joined_at}T00:00:00Z`).toISOString() : null,
      manager_employee_id: form.manager_employee_id ? Number(form.manager_employee_id) : null,
      hr_position_id: form.hr_position_id ? Number(form.hr_position_id) : null,
      hr_profile_json: Object.fromEntries(Object.entries(form.profile).filter(([, value]) => value !== "")),
    };
    try {
      if (editing === "new") await api.post("/api/employees", payload);
      else await api.patch(`/api/employees/${editing?.id}`, payload);
      setEmployees([]); setPage(1); if (page === 1) await mutate(); setEditing(null);
    } catch (saveError: unknown) { setMessage(String((saveError as Error)?.message || saveError)); }
    finally { setSaving(false); }
  }

  return <div>
    <HrHeader title={t("page.hrEmployees.title")} subtitle={t("page.hrEmployees.subtitle")} actions={<><button className="btn" onClick={downloadEmployees} disabled={exporting}>{t(exporting ? "employeeExport.loading" : "employeeExport.download")}</button><button className="btn btn-primary" onClick={() => open()}>{t("page.hrEmployees.add")}</button></>} />
    {exportError && <p role="alert" className="mb-4 text-sm text-red-600">{exportError}</p>}
    <MetricGrid items={[{ label: t("page.hrEmployees.total"), value: activePageData?.total ?? "—" }, { label: t("page.hrEmployees.active"), value: activePageData?.active_total ?? "—" }, { label: t("page.hrEmployees.inactiveTotal"), value: activePageData?.inactive_total ?? "—" }, { label: t("page.hrEmployees.coverage"), value: activePageData?.profile_coverage_percent == null ? "—" : `${activePageData.profile_coverage_percent}%` }]} />
    <div className="card mb-4 p-4"><input className="input max-w-xl" placeholder={t("page.hrEmployees.search")} value={query} onChange={(event) => changeQuery(event.target.value)} /></div>
    <LoadState loading={isLoading || !activePageData} error={error} empty={!isLoading && Boolean(activePageData) && filtered.length === 0}>
      <div className="card overflow-x-auto"><table className="table min-w-[900px]"><thead><tr><th>{t("page.hrEmployees.employee")}</th><th>{t("page.hrEmployees.employeeId")}</th><th>{t("page.hrEmployees.department")}</th><th>{t("page.hrEmployees.position")}</th><th>{t("page.hrEmployees.manager")}</th><th>{t("page.hrEmployees.status")}</th><th>{t("page.hrEmployees.hireDate")}</th><th /></tr></thead><tbody>
        {filtered.map((employee) => <tr key={employee.id}>
          <td><div className="flex items-center gap-3">{String(employee.hr_profile_json?.photo_url || "") ? <img className="h-9 w-9 rounded-full object-cover" src={String(employee.hr_profile_json.photo_url)} alt="" /> : <div className="grid h-9 w-9 place-items-center rounded-full bg-[#ecebe3] text-xs font-semibold">{employee.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("")}</div>}<div><div className="font-medium">{employee.full_name}</div><div className="text-xs text-[#8a8472]">{employee.phone || String(employee.hr_profile_json?.email || "—")}</div></div></div></td>
          <td className="font-mono">{effectiveEmployeeNumber(employee)}</td>
          <td>{departments?.find((row) => row.id === employee.department_id)?.name || t("page.hrEmployees.unassigned")}</td>
          <td>{employee.position_name || employee.position || "—"}</td>
          <td>{employee.manager_name || "—"}</td>
          <td><span className={`badge ${employee.status === "active" ? "badge-green" : "badge-red"}`}>{employeeStatusLabel(employee.status)}</span></td>
          <td>{employee.joined_at ? new Date(employee.joined_at).toLocaleDateString({ en: "en-GB", ru: "ru-RU", uz: "uz-UZ" }[lang]) : "—"}</td>
          <td><button className="text-brand-600 hover:underline" onClick={() => open(employee)}>{t("page.hrEmployees.openProfile")}</button></td>
        </tr>)}
      </tbody></table></div>
    </LoadState>

    <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? t("page.hrEmployees.newEmployee") : t("page.hrEmployees.profileTitle", { name: form.full_name })} wide>
      <form onSubmit={save} className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label><span className="label">{t("field.employeeNo")}</span><input className="input" inputMode="numeric" pattern="[0-9]+" value={form.employee_no} onChange={(e) => setForm({ ...form, employee_no: e.target.value })} /></label>
          <label className="lg:col-span-2"><span className="label">{t("page.hrEmployees.fullName")}</span><input className="input" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
          <label><span className="label">{t("page.hrEmployees.phone")}</span><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <label><span className="label">{t("page.hrEmployees.department")}</span><select className="input" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })}><option value="">{t("page.hrEmployees.unassigned")}</option>{departments?.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label><span className="label">{t("page.hrEmployees.positionSearch")}</span><input className="input" value={positionSearch} onChange={(event) => setPositionSearch(event.target.value)} /></label>
          <label><span className="label">{t("page.hrEmployees.staffingPosition")}</span><select className="input" value={form.hr_position_id} onChange={(e) => setForm({ ...form, hr_position_id: e.target.value })}><option value="">{t("page.hrEmployees.unassigned")}</option>{positions?.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label><span className="label">{t("page.hrEmployees.positionLabel")}</span><input className="input" value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} /></label>
          <label><span className="label">{t("page.hrEmployees.managerSearch")}</span><input className="input" type="search" value={managerSearch} onChange={(event) => setManagerSearch(event.target.value)} placeholder={t("page.payroll.searchEmployee")} /></label>
          <label><span className="label">{t("page.hrEmployees.manager")}</span><select className="input" value={form.manager_employee_id} onChange={(e) => setForm({ ...form, manager_employee_id: e.target.value })}><option value="">—</option>{managerOptions?.rows.filter((row) => row.id !== (editing === "new" ? -1 : editing?.id)).map((row) => <option key={row.id} value={row.id}>{row.full_name}</option>)}</select>{managerOptions?.has_more && <span className="mt-1 block text-xs text-[#8a8472]">{t("page.hrEmployees.refineManagerSearch")}</span>}</label>
          <label><span className="label">{t("page.hrEmployees.employmentStatus")}</span><select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}><option value="active">{t("page.hrEmployees.active")}</option><option value="inactive">{t("page.hrEmployees.inactive")}</option><option value="on_leave">{t("page.hrEmployees.on_leave")}</option><option value="terminated">{t("page.hrEmployees.terminated")}</option></select></label>
          <label><span className="label">{t("page.hrEmployees.hireDate")}</span><input className="input" type="date" value={form.joined_at} onChange={(e) => setForm({ ...form, joined_at: e.target.value })} /></label>
          <label><span className="label">{t("page.hrEmployees.salary")}</span><input className="input" type="number" min="0" step="0.01" value={form.salary} onChange={(e) => setForm({ ...form, salary: e.target.value })} /></label>
        </div>
        <div className="border-t border-[#ecebe3] pt-4">
          <div className="mb-4 flex flex-wrap gap-2">{(Object.keys(PROFILE_FIELDS) as (keyof typeof PROFILE_FIELDS)[]).map((name) => <button type="button" className={`btn ${section === name ? "btn-primary" : ""}`} onClick={() => setSection(name)} key={name}>{t(`page.hrEmployees.section${name}`)}</button>)}</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{PROFILE_FIELDS[section].map(([key, label, type]) => <label key={key}><span className="label">{t(label)}</span><input className="input" type={type} step={type === "number" ? "0.25" : undefined} value={profileValue(key)} onChange={(e) => setProfile(key, e.target.value)} /></label>)}</div>
        </div>
        {message && <div className="text-sm text-red-700">{message}</div>}
        <div className="flex flex-wrap justify-end gap-2"><button type="button" className="btn" onClick={() => setEditing(null)}>{t("common.cancel")}</button><button className="btn btn-primary" disabled={saving}>{t(saving ? "page.hrEmployees.saving" : "page.hrEmployees.save")}</button></div>
      </form>
    </Modal>
    {activePageData?.has_more && <button className="btn mt-4" onClick={() => setPage((current) => current + 1)} disabled={isLoading}>{t("page.hrEmployees.loadMore")}</button>}
  </div>;
}
