"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { firstGradeText } from "@/lib/firstGradeText";

type Option = { model_id: number; model_code: string; color: string; size: string; available: number };
const optionKey = (row: Option) => JSON.stringify([row.model_id, row.color, row.size]);
export default function FirstGradeSale() {
  const { lang } = useT(); const copy = firstGradeText[lang]; const router = useRouter();
  const { data: options, error } = useSWR<Option[]>("/api/sales-orders/first-grade-options", fetcher);
  const { data: customers, error: customerError } = useSWR<{ id: number; name: string }[]>("/api/customers", fetcher);
  const [customer, setCustomer] = useState(""); const [values, setValues] = useState<Record<string, { quantity: string; price: string }>>({});
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");
  const selected = (options || []).map(option => ({ ...option, ...values[optionKey(option)] })).filter(row => Number(row.quantity) > 0);
  return <main className="space-y-4"><h1 className="app-page-title">{copy.title} · {copy.sale}</h1><Link className="btn" href="/warehouse-stock?stock_kind=first_grade">{copy.stock}</Link>
    {(error || customerError || message) && <p role="alert" className="text-red-700">{message || error?.message || customerError?.message}</p>}
    {!options && !error && <p>{copy.loading}</p>}
    <form className="card p-4 space-y-4" onSubmit={async event => {
      event.preventDefault(); if (busy || !selected.length) return; setBusy(true); setMessage("");
      try {
        const order = await api.post<{ id: number }>("/api/sales-orders", { order_type: "branded_stock_sale", customer_id: Number(customer), items: selected.map(row => ({ model_id: row.model_id, color: row.color, size: row.size, quantity: Number(row.quantity), unit_price: Number(row.price), source_type: "first_grade" })) });
        router.push(`/sales-orders/${order.id}`);
      } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); setBusy(false); }
    }}>
      <label className="block max-w-md"><span className="label">{copy.customer}</span><select className="input" required value={customer} disabled={busy} onChange={e => setCustomer(e.target.value)}><option value="">{copy.select}</option>{customers?.map(row => <option value={row.id} key={row.id}>{row.name}</option>)}</select></label>
      <div className="overflow-x-auto"><table className="table text-sm"><thead><tr><th>{copy.model}</th><th>{copy.contents}</th><th>{copy.available}</th><th>{copy.total}</th><th>{copy.price}</th></tr></thead><tbody>
        {options?.map(row => <tr key={`${row.model_id}:${row.color}:${row.size}`}><td>{row.model_code}</td><td>{row.color} · {row.size}</td><td>{row.available}</td><td><input className="input w-28" aria-label={`${copy.total} ${row.model_code} ${row.size}`} type="number" min="0" max={row.available} step="1" disabled={busy} value={values[optionKey(row)]?.quantity || ""} onChange={e => setValues({ ...values, [optionKey(row)]: { price: values[optionKey(row)]?.price || "", quantity: e.target.value } })} /></td><td><input className="input w-32" aria-label={`${copy.price} ${row.model_code} ${row.size}`} type="number" min="0" step="0.01" required={Number(values[optionKey(row)]?.quantity) > 0} disabled={busy} value={values[optionKey(row)]?.price || ""} onChange={e => setValues({ ...values, [optionKey(row)]: { quantity: values[optionKey(row)]?.quantity || "", price: e.target.value } })} /></td></tr>)}
        {options?.length === 0 && <tr><td colSpan={5}>{copy.empty}</td></tr>}
      </tbody></table></div><button className="btn btn-primary" disabled={busy || !selected.length || !customer}>{copy.saveSale}</button>
    </form>
  </main>;
}
