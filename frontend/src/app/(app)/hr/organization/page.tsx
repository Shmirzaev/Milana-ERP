"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import Modal from "@/components/Modal";
import { HrHeader, LoadState, MetricGrid } from "@/components/hr/HrUi";

const PAGE_SIZE = 50;
type Unit = { id: number; parent_id: number | null; parent_name: string | null; department_id: number | null; manager_employee_id: number | null; manager_name: string | null; unit_type: string; name: string; code: string | null; sort_order: number };
type Employee = { id: number; employee_no: string | null; full_name: string; manager_employee_id: number | null; hr_position_id: number | null; position: string | null; status: string };
type Response = { units: Unit[]; employees: Employee[]; page: number; page_size: number; search: string; unit_total: number; employee_total: number; units_have_more: boolean; employees_have_more: boolean; active_employee_total: number; vacant_employee_total: number; manager_unit_total: number };

function appendById<T extends { id: number }>(existing: T[], incoming: T[]) {
  const rows = new Map(existing.map((row) => [row.id, row]));
  for (const row of incoming) rows.set(row.id, row);
  return Array.from(rows.values());
}

export default function OrganizationPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [units, setUnits] = useState<Unit[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({ parent_id: "", parent_label: "", manager_employee_id: "", manager_label: "", unit_type: "section", name: "", code: "" });
  const key = `/api/hr/organization?page=${page}&page_size=${PAGE_SIZE}&search=${encodeURIComponent(search)}`;
  const { data, error, isLoading, mutate } = useSWR<Response>(key, fetcher);

  useEffect(() => {
    if (!data) return;
    if (page === 1) {
      setUnits(data.units);
      setEmployees(data.employees);
    } else {
      setUnits((current) => appendById(current, data.units));
      setEmployees((current) => appendById(current, data.employees));
    }
  }, [data, page]);

  const unitIds = useMemo(() => new Set(units.map((unit) => unit.id)), [units]);
  const roots = useMemo(() => units.filter((unit) => !unit.parent_id || !unitIds.has(unit.parent_id)), [units, unitIds]);
  function renderUnit(unit: Unit, depth = 0): React.ReactNode {
    const children = units.filter((row) => row.parent_id === unit.id);
    return <div key={unit.id} style={{ marginLeft: depth * 24 }} className="mt-3"><div className="rounded-lg border border-[#dedbd0] bg-white p-3"><div className="text-[10px] font-bold uppercase tracking-wide text-[#8a8472]">{unit.unit_type}</div><div className="font-semibold">{unit.name}</div>{unit.parent_id && !unitIds.has(unit.parent_id) && <div className="mt-1 text-xs text-[#6d6757]">Parent: {unit.parent_name || "Historical parent"}</div>}<div className="mt-1 text-xs text-[#6d6757]">Manager: {unit.manager_name || "Not assigned"}</div></div>{children.map((child) => renderUnit(child, depth + 1))}</div>;
  }
  function changeSearch(value: string) {
    setUnits([]);
    setEmployees([]);
    setPage(1);
    setSearch(value);
  }
  async function create(event: React.FormEvent) {
    event.preventDefault();
    setMessage("");
    try {
      await api.post("/api/hr/organization", { parent_id: form.parent_id ? Number(form.parent_id) : null, department_id: null, manager_employee_id: form.manager_employee_id ? Number(form.manager_employee_id) : null, unit_type: form.unit_type, name: form.name, code: form.code || null, sort_order: 0 });
      setOpen(false);
      setForm({ parent_id: "", parent_label: "", manager_employee_id: "", manager_label: "", unit_type: "section", name: "", code: "" });
      setUnits([]);
      setEmployees([]);
      if (page === 1) await mutate();
      else setPage(1);
    } catch (e: unknown) {
      setMessage(String((e as Error)?.message || e));
    }
  }

  return <div>
    <HrHeader title="Organization Structure" subtitle="Company → Factory → Department → Section → Team → Position → Employee" actions={<button className="btn btn-primary" onClick={() => setOpen(true)}>Add organization unit</button>} />
    <MetricGrid items={[{ label: "Organization units", value: data?.unit_total ?? "—" }, { label: "Active employees", value: data?.active_employee_total ?? "—" }, { label: "Without staffing position", value: data?.vacant_employee_total ?? "—" }, { label: "Managers assigned", value: data?.manager_unit_total ?? "—" }]} />
    <label className="mb-4 block max-w-xl"><span className="label">Search organization units and employees</span><input className="input" type="search" value={search} onChange={(event) => changeSearch(event.target.value)} placeholder="Name, employee number, position, or unit code" /></label>
    {data && <p className="mb-3 text-sm text-[#6d6757]">{data.unit_total} units · {data.employee_total} employees match{search ? ` “${search}”` : ""}. Loaded {units.length} units and {employees.length} employees.</p>}
    <LoadState loading={isLoading} error={error} empty={!isLoading && !roots.length}><div className="card p-5"><div className="overflow-x-auto pb-3">{roots.map((unit) => renderUnit(unit))}</div></div></LoadState>
    {employees.length > 0 && <div className="mt-3 text-sm text-[#6d6757]">Employee directory options loaded: {employees.length} of {data?.employee_total ?? employees.length}. Search by employee name or number to find older assignments.</div>}
    {(data?.units_have_more || data?.employees_have_more) && <button className="btn mt-4" onClick={() => setPage((current) => current + 1)} disabled={isLoading}>Load more</button>}
    <Modal open={open} onClose={() => setOpen(false)} title="Add organization unit"><form className="space-y-3" onSubmit={create}><label><span className="label">Type</span><select className="input" value={form.unit_type} onChange={(e) => setForm({ ...form, unit_type: e.target.value })}>{["company", "factory", "department", "section", "team"].map((v) => <option key={v}>{v}</option>)}</select></label><label><span className="label">Name</span><input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label><span className="label">Find parent or manager</span><input className="input" type="search" value={search} onChange={(event) => changeSearch(event.target.value)} placeholder="Search unit name, employee name, or number" /></label><label><span className="label">Parent unit</span><select className="input" value={form.parent_id} onChange={(e) => { const row = units.find((unit) => String(unit.id) === e.target.value); setForm({ ...form, parent_id: e.target.value, parent_label: row ? `${row.unit_type}: ${row.name}` : "" }); }}><option value="">Root level</option>{form.parent_id && !units.some((row) => String(row.id) === form.parent_id) && <option value={form.parent_id}>{form.parent_label}</option>}{units.map((row) => <option value={row.id} key={row.id}>{row.unit_type}: {row.name}</option>)}</select></label><label><span className="label">Manager</span><select className="input" value={form.manager_employee_id} onChange={(e) => { const row = employees.find((employee) => String(employee.id) === e.target.value); setForm({ ...form, manager_employee_id: e.target.value, manager_label: row ? `${row.full_name} · ${row.employee_no || "No employee number"}` : "" }); }}><option value="">Not assigned</option>{form.manager_employee_id && !employees.some((row) => String(row.id) === form.manager_employee_id) && <option value={form.manager_employee_id}>{form.manager_label}</option>}{employees.map((row) => <option value={row.id} key={row.id}>{row.full_name} · {row.employee_no || "No employee number"}</option>)}</select></label>{(data?.units_have_more || data?.employees_have_more) && <button className="btn" type="button" onClick={() => setPage((current) => current + 1)}>Load more parent and manager options</button>}<label><span className="label">Code</span><input className="input" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></label>{message && <div className="text-sm text-red-700">{message}</div>}<div className="flex justify-end gap-2"><button className="btn" type="button" onClick={() => setOpen(false)}>Cancel</button><button className="btn btn-primary">Add unit</button></div></form></Modal>
  </div>;
}
