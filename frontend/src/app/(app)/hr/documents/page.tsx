"use client";

import { useState } from "react";
import useSWRInfinite from "swr/infinite";
import { api, fetcher } from "@/lib/api";
import Modal from "@/components/Modal";
import { HrHeader, LoadState, MetricGrid } from "@/components/hr/HrUi";
import DocumentEmployeeSelect, { type DocumentEmployee } from "@/components/hr/DocumentEmployeeSelect";

type Document = {
  id: number;
  employee_id: number;
  employee_name: string;
  category: string;
  title: string;
  original_name: string;
  size_bytes: number;
  expires_on: string | null;
  created_at: string;
  download_url: string;
};
type DocumentPage = {
  rows: Document[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  metrics: { employee_folders: number; archive_size_bytes: number; expiring_in_30_days: number };
};

const CATEGORIES = [
  "employment_contract", "passport_id", "diploma", "certificate", "employment_order",
  "salary_amendment", "leave", "disciplinary", "training", "resignation", "other",
];

export default function DocumentsPage() {
  const { data: pages, error, isLoading, mutate, setSize } = useSWRInfinite<DocumentPage>(
    (index) => `/api/hr/documents?page=${index + 1}&page_size=100`,
    fetcher,
  );
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [selectedEmployee, setSelectedEmployee] = useState<DocumentEmployee | null>(null);
  const [form, setForm] = useState({
    employee_id: "", category: "employment_contract", title: "", expires_on: "", file: null as File | null,
  });
  const data = pages?.flatMap((page) => page.rows) || [];
  const lastPage = pages?.[pages.length - 1];
  const metrics = pages?.[0]?.metrics;

  const loadMore = () => {
    if (lastPage?.has_more) void setSize((pages?.length || 0) + 1);
  };

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!form.employee_id) {
      setMessage("Select employee");
      return;
    }
    if (!form.file) return;
    setBusy(true);
    setMessage("");
    const body = new FormData();
    body.append("employee_id", form.employee_id);
    body.append("category", form.category);
    body.append("title", form.title);
    if (form.expires_on) body.append("expires_on", form.expires_on);
    body.append("file", form.file);
    try {
      await api.postForm("/api/hr/documents", body);
      await mutate();
      setOpen(false);
    } catch (error: unknown) {
      setMessage(String((error as Error)?.message || error));
    } finally {
      setBusy(false);
    }
  }

  return <div>
    <HrHeader
      title="Employee Documents"
      subtitle="Secure, factory-scoped digital personnel archive."
      actions={<button className="btn btn-primary" onClick={() => setOpen(true)}>Upload document</button>}
    />
    <MetricGrid items={[
      { label: "Documents", value: pages?.[0]?.total ?? "—" },
      { label: "Employee folders", value: metrics?.employee_folders ?? "—" },
      { label: "Expiring in 30 days", value: metrics?.expiring_in_30_days ?? "—" },
      { label: "Archive size", value: metrics ? `${(metrics.archive_size_bytes / 1048576).toFixed(1)} MB` : "—" },
    ]} />
    <LoadState loading={isLoading} error={error} empty={!isLoading && !data.length}>
      <div className="card overflow-x-auto">
        <table className="table">
          <thead><tr><th>Employee</th><th>Category</th><th>Document</th><th>Expiry</th><th>Uploaded</th><th /></tr></thead>
          <tbody>{data.map((row) => <tr key={row.id}>
            <td>{row.employee_name}</td>
            <td className="capitalize">{row.category.replaceAll("_", " ")}</td>
            <td><div className="font-medium">{row.title}</div><div className="text-xs text-[#8a8472]">{row.original_name}</div></td>
            <td>{row.expires_on ? new Date(row.expires_on).toLocaleDateString() : "—"}</td>
            <td>{new Date(row.created_at).toLocaleDateString()}</td>
            <td><a className="text-brand-600 hover:underline" href={row.download_url}>Download</a></td>
          </tr>)}</tbody>
        </table>
        {lastPage?.has_more && <button className="btn mt-3" onClick={loadMore}>Load more</button>}
      </div>
    </LoadState>
    <Modal open={open} onClose={() => setOpen(false)} title="Upload employee document">
      <form className="space-y-3" onSubmit={upload}>
        <DocumentEmployeeSelect
          enabled={open}
          value={Number(form.employee_id) || null}
          selectedEmployee={selectedEmployee}
          onChange={(employee) => {
            setSelectedEmployee(employee);
            setForm((current) => ({ ...current, employee_id: employee ? String(employee.id) : "" }));
          }}
        />
        <select className="input" value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })}>
          {CATEGORIES.map((category) => <option key={category} value={category}>{category.replaceAll("_", " ")}</option>)}
        </select>
        <input className="input" required placeholder="Document title" value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} />
        <label><span className="label">Expiration date (optional)</span><input className="input" type="date" value={form.expires_on} onChange={(event) => setForm({ ...form, expires_on: event.target.value })} /></label>
        <input className="input" required type="file" onChange={(event) => setForm({ ...form, file: event.target.files?.[0] || null })} />
        {message && <div className="text-sm text-red-700">{message}</div>}
        <button className="btn btn-primary w-full" disabled={busy}>{busy ? "Uploading…" : "Upload securely"}</button>
      </form>
    </Modal>
  </div>;
}
