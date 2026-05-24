"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

export default function CustomerDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { t } = useT();
  const { data: customer, mutate } = useSWR<any>(`/api/customers/${id}`, fetcher);
  const { data: orders } = useSWR<any[]>(`/api/customers/${id}/orders`, fetcher);
  const [form, setForm] = useState({ name: "", phone: "", email: "", address: "", notes: "" });
  const [msg, setMsg] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!customer) return;
    setForm({
      name: customer.name || "",
      phone: customer.phone || "",
      email: customer.email || "",
      address: customer.address || "",
      notes: customer.notes || "",
    });
  }, [customer]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    const next: Record<string, string> = {};
    if (!form.name.trim()) next.name = "Name is required.";
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) next.email = "Enter a valid email.";
    setErrors(next);
    if (Object.keys(next).length) return;
    try {
      await api.patch(`/api/customers/${id}`, form);
      setMsg("Saved.");
      mutate();
    } catch (err: any) {
      setMsg(err.message);
    }
  }

  if (!customer) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader title={customer.name} subtitle="Customer profile" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[420px_1fr]">
        <form onSubmit={save} className="card p-4 space-y-3">
          <div><label className="label">{t("common.name")}</label><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          {errors.name && <div className="text-xs text-red-600">{errors.name}</div>}
          <div><label className="label">{t("field.phone")}</label><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
          <div><label className="label">{t("field.email")}</label><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          {errors.email && <div className="text-xs text-red-600">{errors.email}</div>}
          <div><label className="label">{t("field.address")}</label><input className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></div>
          <div><label className="label">{t("field.notes")}</label><textarea className="input min-h-24" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          {msg && <div className={`text-sm ${msg === "Saved." ? "text-green-700" : "text-red-600"}`}>{msg}</div>}
          <div className="flex justify-end"><button className="btn btn-primary">{t("btn.save")}</button></div>
        </form>

        <section className="card overflow-x-auto">
          <div className="border-b border-[#ecebe3] px-4 py-3">
            <h2 className="app-card-title">Order history</h2>
          </div>
          <table className="table">
            <thead><tr><th>{t("field.orderNo")}</th><th>Date</th><th>{t("field.total")}</th><th>{t("field.status")}</th></tr></thead>
            <tbody>
              {(orders || []).map((o) => (
                <tr key={o.id}>
                  <td><a className="text-brand-600 hover:underline" href={`/sales-orders/${o.id}`}>{o.order_no}</a></td>
                  <td>{o.date ? new Date(o.date).toLocaleDateString() : "-"}</td>
                  <td>${Number(o.total || 0).toFixed(2)}</td>
                  <td><span className="badge">{statusLabel(o.status, t)}</span></td>
                </tr>
              ))}
              {orders && orders.length === 0 && <tr><td colSpan={4} className="text-sm text-slate-500">No sales orders linked to this customer.</td></tr>}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
