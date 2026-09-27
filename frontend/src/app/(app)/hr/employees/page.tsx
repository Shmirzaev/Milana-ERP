"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import Modal from "@/components/Modal";
import { HrHeader, LoadState, MetricGrid } from "@/components/hr/HrUi";
import { useT } from "@/lib/i18n";

type Dept = { id: number; name: string; is_active?: boolean };
type Position = { id: number; name: string };
type Employee = {
  id: number; factory_code: string; employee_no: string | null; full_name: string;
  department_id: number | null; position: string | null; phone: string | null;
  salary: number | null; status: string; joined_at: string | null;
  manager_employee_id: number | null; manager_name?: string | null; hr_position_id: number | null; hr_profile_json: Record<string, unknown>;
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
    ["photo_url", "Photo URL", "url"], ["date_of_birth", "Date of birth", "date"],
    ["gender", "Gender", "text"], ["email", "Email", "email"], ["address", "Address", "text"],
    ["emergency_contact", "Emergency contact", "text"], ["nationality", "Nationality", "text"],
  ],
  Employment: [
    ["company", "Company", "text"], ["branch", "Factory / branch", "text"], ["section", "Section", "text"],
    ["grade_level", "Grade / level", "text"], ["employment_type", "Employment type", "text"],
    ["probation_end", "Probation ending", "date"], ["work_schedule", "Work schedule", "text"],
    ["shift", "Shift", "text"], ["workplace", "Workplace / workstation", "text"],
    ["scheduled_daily_hours", "Scheduled daily hours", "number"],
  ],
  Financial: [
    ["rate_type", "Hourly / monthly rate", "text"], ["bonus_scheme", "Bonus scheme", "text"],
    ["bank_details", "Bank details", "text"], ["payroll_id", "Payroll ID", "text"],
  ],
} as const;

const EMPTY: FormState = { employee_no: "", full_name: "", department_id: "", position: "", phone: "", salary: "", status: "active", joined_at: "", manager_employee_id: "", hr_position_id: "", profile: {} };

function effectiveEmployeeNumber(employee: Pick<Employee, "id" | "employee_no">): string {
  const configured = String(employee.employee_no || "").trim();
  return configured || `EMP-${String(employee.id).padStart(4, "0")}`;
}

function toForm(employee?: Employee | null): FormState {
  if (!employee) return structuredClone(EMPTY);
  const profile: Record<string, string> = {};
  Object.entries(employee.hr_profile_json || {}).forEach(([key, value]) => { profile[key] = value == null ? "" : String(value); });
  return { employee_no: employee.employee_no || "", full_name: employee.full_name, department_id: employee.department_id ? String(employee.department_id) : "", position: employee.position || "", phone: employee.phone || "", salary: employee.salary == null ? "" : String(employee.salary), status: employee.status, joined_at: employee.joined_at ? employee.joined_at.slice(0, 10) : "", manager_employee_id: employee.manager_employee_id ? String(employee.manager_employee_id) : "", hr_position_id: employee.hr_position_id ? String(employee.hr_position_id) : "", profile };
}

export default function EmployeesPage() {
  const { t } = useT();
  const PAGE_SIZE = 50;
  const [page, setPage] = useState(1);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [query, setQuery] = useState("");
  const { data, error, isLoading, mutate } = useSWR<EmployeePage>(`/api/employees?page=${page}&page_size=${PAGE_SIZE}&search=${encodeURIComponent(query)}`, fetcher);
  const { data: departments } = useSWR<Dept[]>("/api/departments", fetcher);
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const positionDirectoryKey = editing !== null || employees.some((employee) => employee.hr_position_id != null)
    ? "/api/hr/positions"
    : null;
  const { data: positions } = useSWR<Position[]>(positionDirectoryKey, fetcher);
  const [managerSearch, setManagerSearch] = useState("");
  const managerSelected = form.manager_employee_id ? Number(form.manager_employee_id) : null;
  const managerKey = editing !== null
    ? `/api/employees/manager-options?search=${encodeURIComponent(managerSearch)}${managerSelected ? `&selected_id=${managerSelected}` : ""}`
    : null;
  const { data: managerOptions } = useSWR<ManagerOptions>(managerKey, fetcher);
  const [section, setSection] = useState<keyof typeof PROFILE_FIELDS>("Personal");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!data || data.page !== page || data.search !== query.trim()) return;
    setEmployees((current) => page === 1
      ? data.rows
      : Array.from(new Map([...current, ...data.rows].map((row) => [row.id, row])).values()));
  }, [data, page, query]);
  const activePageData = data?.page === page && data.search === query.trim() ? data : undefined;
  const filtered = useMemo(() => employees, [employees]);
  function changeQuery(value: string) { setEmployees([]); setPage(1); setQuery(value); }

  function open(employee?: Employee) { setEditing(employee || "new"); setForm(toForm(employee)); setManagerSearch(""); setSection("Personal"); setMessage(""); }
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
    <HrHeader title="Employees" subtitle="Central employee database and complete digital personnel profiles." actions={<button className="btn btn-primary" onClick={() => open()}>Add employee</button>} />
    <MetricGrid items={[{ label: "Total profiles", value: activePageData?.total ?? "—" }, { label: "Active", value: activePageData?.active_total ?? "—" }, { label: "Inactive / leave", value: activePageData?.inactive_total ?? "—" }, { label: "Profile coverage", value: activePageData?.profile_coverage_percent == null ? "—" : `${activePageData.profile_coverage_percent}%` }]} />
    <div className="card mb-4 p-4"><input className="input max-w-xl" placeholder="Search by employee ID, name or position" value={query} onChange={(event) => changeQuery(event.target.value)} /></div>
    <LoadState loading={isLoading || !activePageData} error={error} empty={!isLoading && Boolean(activePageData) && filtered.length === 0}>
      <div className="card overflow-x-auto"><table className="table min-w-[900px]"><thead><tr><th>Employee</th><th>Employee ID</th><th>Department</th><th>Position</th><th>Manager</th><th>Status</th><th>Hire date</th><th /></tr></thead><tbody>
        {filtered.map((employee) => <tr key={employee.id}>
          <td><div className="flex items-center gap-3">{String(employee.hr_profile_json?.photo_url || "") ? <img className="h-9 w-9 rounded-full object-cover" src={String(employee.hr_profile_json.photo_url)} alt="" /> : <div className="grid h-9 w-9 place-items-center rounded-full bg-[#ecebe3] text-xs font-semibold">{employee.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("")}</div>}<div><div className="font-medium">{employee.full_name}</div><div className="text-xs text-[#8a8472]">{employee.phone || String(employee.hr_profile_json?.email || "—")}</div></div></div></td>
          <td className="font-mono">{effectiveEmployeeNumber(employee)}</td>
          <td>{departments?.find((row) => row.id === employee.department_id)?.name || "Unassigned"}</td>
          <td>{positions?.find((row) => row.id === employee.hr_position_id)?.name || employee.position || "—"}</td>
          <td>{employee.manager_name || "—"}</td>
          <td><span className={`badge ${employee.status === "active" ? "badge-green" : "badge-red"}`}>{employee.status.replaceAll("_", " ")}</span></td>
          <td>{employee.joined_at ? new Date(employee.joined_at).toLocaleDateString() : "—"}</td>
          <td><button className="text-brand-600 hover:underline" onClick={() => open(employee)}>Open profile</button></td>
        </tr>)}
      </tbody></table></div>
    </LoadState>

    <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "New employee" : `Employee profile — ${form.full_name}`} wide>
      <form onSubmit={save} className="space-y-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label><span className="label">{t("field.employeeNo")}</span><input className="input" inputMode="numeric" pattern="[0-9]+" value={form.employee_no} onChange={(e) => setForm({ ...form, employee_no: e.target.value })} /></label>
          <label className="lg:col-span-2"><span className="label">Full name</span><input className="input" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></label>
          <label><span className="label">Phone</span><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></label>
          <label><span className="label">Department</span><select className="input" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })}><option value="">Unassigned</option>{departments?.filter((row) => row.is_active !== false || row.id === Number(form.department_id)).map((row) => <option key={row.id} value={row.id}>{row.name}{row.is_active === false ? " (Inactive)" : ""}</option>)}</select></label>
          <label><span className="label">Staffing position</span><select className="input" value={form.hr_position_id} onChange={(e) => setForm({ ...form, hr_position_id: e.target.value })}><option value="">Unassigned</option>{positions?.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
          <label><span className="label">Position label</span><input className="input" value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} /></label>
          <label><span className="label">{t("page.hrEmployees.managerSearch")}</span><input className="input" type="search" value={managerSearch} onChange={(event) => setManagerSearch(event.target.value)} placeholder={t("page.payroll.searchEmployee")} /></label>
          <label><span className="label">{t("page.hrEmployees.manager")}</span><select className="input" value={form.manager_employee_id} onChange={(e) => setForm({ ...form, manager_employee_id: e.target.value })}><option value="">—</option>{managerOptions?.rows.filter((row) => row.id !== (editing === "new" ? -1 : editing?.id)).map((row) => <option key={row.id} value={row.id}>{row.full_name}</option>)}</select>{managerOptions?.has_more && <span className="mt-1 block text-xs text-[#8a8472]">{t("page.hrEmployees.refineManagerSearch")}</span>}</label>
          <label><span className="label">Employment status</span><select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}><option value="active">Active</option><option value="inactive">Inactive</option><option value="on_leave">On leave</option><option value="terminated">Terminated</option></select></label>
          <label><span className="label">Hire date</span><input className="input" type="date" value={form.joined_at} onChange={(e) => setForm({ ...form, joined_at: e.target.value })} /></label>
          <label><span className="label">Salary</span><input className="input" type="number" min="0" step="0.01" value={form.salary} onChange={(e) => setForm({ ...form, salary: e.target.value })} /></label>
        </div>
        <div className="border-t border-[#ecebe3] pt-4">
          <div className="mb-4 flex gap-2">{(Object.keys(PROFILE_FIELDS) as (keyof typeof PROFILE_FIELDS)[]).map((name) => <button type="button" className={`btn ${section === name ? "btn-primary" : ""}`} onClick={() => setSection(name)} key={name}>{name}</button>)}</div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{PROFILE_FIELDS[section].map(([key, label, type]) => <label key={key}><span className="label">{label}</span><input className="input" type={type} step={type === "number" ? "0.25" : undefined} value={profileValue(key)} onChange={(e) => setProfile(key, e.target.value)} /></label>)}</div>
        </div>
        {message && <div className="text-sm text-red-700">{message}</div>}
        <div className="flex justify-end gap-2"><button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button><button className="btn btn-primary" disabled={saving}>{saving ? "Saving…" : "Save employee profile"}</button></div>
      </form>
    </Modal>
    {activePageData?.has_more && <button className="btn mt-4" onClick={() => setPage((current) => current + 1)} disabled={isLoading}>{t("page.hrEmployees.loadMore")}</button>}
  </div>;
}
