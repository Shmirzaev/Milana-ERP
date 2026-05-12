"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";

type Dept = { id: number; name: string };
type Employee = {
  id: number;
  full_name: string;
  position: string | null;
  phone: string | null;
  salary: number | null;
  department_id: number | null;
  status: string;
};

const EMPTY = {
  full_name: "",
  position: "",
  phone: "",
  salary: 0,
  department_id: 0,
  status: "active",
};

export default function EmployeesPage() {
  const { t } = useT();
  const { data, mutate } = useSWR<Employee[]>("/api/employees", fetcher);
  const { data: depts } = useSWR<Dept[]>("/api/departments", fetcher);

  const [f, setF] = useState(EMPTY);
  const [createMsg, setCreateMsg] = useState("");

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setCreateMsg("");
    try {
      await api.post("/api/employees", { ...f, department_id: f.department_id || null });
      setF(EMPTY);
      mutate();
    } catch (e: any) {
      setCreateMsg(e.message);
    }
  }

  const [editing, setEditing] = useState<Employee | null>(null);
  const [edit, setEdit] = useState(EMPTY);
  const [editMsg, setEditMsg] = useState("");

  function openEdit(emp: Employee) {
    setEditing(emp);
    setEdit({
      full_name: emp.full_name,
      position: emp.position ?? "",
      phone: emp.phone ?? "",
      salary: emp.salary ?? 0,
      department_id: emp.department_id ?? 0,
      status: emp.status,
    });
    setEditMsg("");
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try {
      await api.patch(`/api/employees/${editing.id}`, {
        full_name: edit.full_name,
        position: edit.position || null,
        phone: edit.phone || null,
        salary: edit.salary || null,
        department_id: edit.department_id || null,
        status: edit.status,
      });
      setEditing(null);
      mutate();
    } catch (e: any) {
      setEditMsg(e.message);
    }
  }

  async function del(emp: Employee) {
    if (!confirm(`${t("common.delete")} ${emp.full_name}?`)) return;
    try {
      await api.del(`/api/employees/${emp.id}`);
      mutate();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.hr.title")} />

      <form onSubmit={create} className="card mb-6 grid grid-cols-1 gap-3 p-4 md:grid-cols-6">
        <input className="input" placeholder={t("field.fullName")} value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} required />
        <input className="input" placeholder={t("field.position")} value={f.position} onChange={(e) => setF({ ...f, position: e.target.value })} />
        <input className="input" placeholder={t("field.phone")} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
        <input className="input" type="number" placeholder={t("field.salary")} value={f.salary} onChange={(e) => setF({ ...f, salary: Number(e.target.value) })} />
        <select className="input" value={f.department_id} onChange={(e) => setF({ ...f, department_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.dept")}</option>
          {depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        <button className="btn btn-primary">{t("btn.add")}</button>
        {createMsg && <div className="text-sm text-red-600 md:col-span-6">{createMsg}</div>}
      </form>

      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.fullName")}</th>
              <th>{t("field.position")}</th>
              <th>{t("field.phone")}</th>
              <th>{t("field.salary")}</th>
              <th>{t("field.department")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {data?.map((emp) => (
              <tr key={emp.id}>
                <td>{emp.full_name}</td>
                <td>{emp.position ?? "-"}</td>
                <td>{emp.phone ?? "-"}</td>
                <td>{emp.salary ?? "-"}</td>
                <td>{depts?.find((d) => d.id === emp.department_id)?.name ?? emp.department_id ?? "-"}</td>
                <td>
                  <span className={`badge ${emp.status === "active" ? "badge-green" : "badge-red"}`}>
                    {emp.status === "active" && t("empStatus.active")}
                    {emp.status === "inactive" && t("empStatus.inactive")}
                    {emp.status === "on_leave" && t("empStatus.onLeave")}
                    {emp.status === "terminated" && t("empStatus.terminated")}
                  </span>
                </td>
                <td className="flex gap-2">
                  <button className="text-brand-600 hover:underline" onClick={() => openEdit(emp)}>{t("btn.edit")}</button>
                  <button className="text-red-600 hover:underline" onClick={() => del(emp)}>{t("btn.delete")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.hr.editTitle", { name: editing?.full_name ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div>
            <label className="label">{t("field.fullName")}</label>
            <input className="input" value={edit.full_name} onChange={(e) => setEdit({ ...edit, full_name: e.target.value })} required />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">{t("field.position")}</label>
              <input className="input" value={edit.position} onChange={(e) => setEdit({ ...edit, position: e.target.value })} />
            </div>
            <div>
              <label className="label">{t("field.phone")}</label>
              <input className="input" value={edit.phone} onChange={(e) => setEdit({ ...edit, phone: e.target.value })} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">{t("field.salary")}</label>
              <input className="input" type="number" value={edit.salary} onChange={(e) => setEdit({ ...edit, salary: Number(e.target.value) })} />
            </div>
            <div>
              <label className="label">{t("field.department")}</label>
              <select className="input" value={edit.department_id} onChange={(e) => setEdit({ ...edit, department_id: Number(e.target.value) })}>
                <option value={0}>-</option>
                {depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="label">{t("common.status")}</label>
            <select className="input" value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              <option value="active">{t("empStatus.active")}</option>
              <option value="inactive">{t("empStatus.inactive")}</option>
              <option value="on_leave">{t("empStatus.onLeave")}</option>
              <option value="terminated">{t("empStatus.terminated")}</option>
            </select>
          </div>
          {editMsg && <div className="text-sm text-red-600">{editMsg}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => setEditing(null)}>{t("btn.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("btn.saveChanges")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
