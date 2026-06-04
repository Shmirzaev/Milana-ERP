"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { Plus } from "lucide-react";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";

type PaymentStatus = "paid" | "partial" | "unpaid" | "no_invoice";
type PaymentRow = {
  id: number;
  amount: number;
  payment_method?: string | null;
  paid_at?: string | null;
  notes?: string | null;
};
type PaymentHistoryRow = PaymentRow & {
  row_key: string;
  order_id: number;
  order_no: string;
  invoice_no: string;
};
type InvoiceRow = {
  id: number;
  invoice_no: string;
  amount: number;
  status: string;
  issued_at?: string | null;
  due_date?: string | null;
  paid_amount: number;
  balance_due: number;
  payments: PaymentRow[];
};
type CustomerOrder = {
  id: number;
  order_no: string;
  date?: string | null;
  total: number;
  status: string;
  invoice_total: number;
  paid_total: number;
  balance_due: number;
  payment_status: PaymentStatus;
  last_payment_at?: string | null;
  invoices: InvoiceRow[];
};
type PaymentForm = {
  amount: number;
  date: string;
  payment_method: string;
  notes: string;
};
type FinanceInvoiceRow = {
  id: number;
  sales_order_id: number;
  invoice_no?: string | null;
  order_no: string;
  customer?: string | null;
  amount: number;
  status: string;
  date?: string | null;
};

function money(value: number) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function paymentStatusLabel(status: PaymentStatus) {
  if (status === "paid") return "Paid";
  if (status === "partial") return "Partial";
  if (status === "unpaid") return "Unpaid";
  return "No invoice";
}

function paymentStatusClass(status: PaymentStatus) {
  if (status === "paid") return "badge-green";
  if (status === "partial") return "badge-blue";
  if (status === "unpaid") return "badge-red";
  return "badge-yellow";
}

function effectiveBalanceDue(order: CustomerOrder) {
  if (order.payment_status === "no_invoice" || !order.invoices?.length) {
    return Math.max(Number(order.total || 0) - Number(order.paid_total || 0), 0);
  }
  return Number(order.balance_due || 0);
}

export default function CustomerDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { t } = useT();
  const { data: customer, mutate } = useSWR<any>(`/api/customers/${id}`, fetcher);
  const { data: orders, mutate: mutateOrders } = useSWR<CustomerOrder[]>(`/api/customers/${id}/orders`, fetcher);
  const { data: financeInvoices, mutate: mutateFinanceInvoices } = useSWR<FinanceInvoiceRow[]>("/api/finance/invoices?limit=200", fetcher);
  const [form, setForm] = useState({ name: "", phone: "", email: "", address: "", notes: "" });
  const [msg, setMsg] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [payingOrder, setPayingOrder] = useState<CustomerOrder | null>(null);
  const [paymentForm, setPaymentForm] = useState<PaymentForm>({
    amount: 0,
    date: new Date().toISOString().slice(0, 10),
    payment_method: "bank_transfer",
    notes: "",
  });
  const [paymentMsg, setPaymentMsg] = useState("");
  const [savingPayment, setSavingPayment] = useState(false);
  const [localPaymentHistory, setLocalPaymentHistory] = useState<PaymentHistoryRow[]>([]);
  const orderRows = useMemo(() => orders || [], [orders]);

  const summary = useMemo(() => {
    return orderRows.reduce(
      (acc, order) => {
        acc.orders += 1;
        acc.orderTotal += Number(order.total || 0);
        acc.invoiced += Number(order.invoice_total || 0);
        acc.paid += Number(order.paid_total || 0);
        acc.balance += effectiveBalanceDue(order);
        if (order.payment_status === "paid") acc.paidOrders += 1;
        if (order.payment_status === "partial" || order.payment_status === "unpaid" || order.payment_status === "no_invoice") acc.openOrders += 1;
        if (order.payment_status === "no_invoice") acc.noInvoiceOrders += 1;
        return acc;
      },
      { orders: 0, orderTotal: 0, invoiced: 0, paid: 0, balance: 0, paidOrders: 0, openOrders: 0, noInvoiceOrders: 0 },
    );
  }, [orderRows]);

  const orderPaymentHistory = useMemo<PaymentHistoryRow[]>(() => {
    return orderRows.flatMap((order) =>
        (order.invoices || []).flatMap((invoice) =>
          (invoice.payments || []).map((payment) => ({
            ...payment,
            row_key: `payment-${payment.id}`,
            order_id: order.id,
            order_no: order.order_no,
            invoice_no: invoice.invoice_no,
          })),
        ),
      );
  }, [orderRows]);

  const financeInvoicePaymentHistory = useMemo<PaymentHistoryRow[]>(() => {
    const orderMap = new Map(orderRows.map((order) => [Number(order.id), order]));
    const invoicesWithPayments = new Set(
      orderRows.flatMap((order) =>
        (order.invoices || [])
          .filter((invoice) => (invoice.payments || []).length > 0)
          .map((invoice) => Number(invoice.id)),
      ),
    );
    return (financeInvoices || [])
      .filter((invoice) => {
        const status = String(invoice.status || "").toLowerCase();
        return orderMap.has(Number(invoice.sales_order_id)) && ["paid", "partial", "partially_paid"].includes(status) && !invoicesWithPayments.has(Number(invoice.id));
      })
      .map((invoice) => {
        const order = orderMap.get(Number(invoice.sales_order_id));
        return {
          id: -Number(invoice.id),
          row_key: `invoice-${invoice.id}`,
          amount: Number(invoice.amount || 0),
          payment_method: "recorded",
          paid_at: invoice.date || null,
          notes: null,
          order_id: Number(invoice.sales_order_id),
          order_no: invoice.order_no || order?.order_no || `#${invoice.sales_order_id}`,
          invoice_no: invoice.invoice_no || `#${invoice.id}`,
        };
      });
  }, [financeInvoices, orderRows]);

  const paymentHistory = useMemo<PaymentHistoryRow[]>(() => {
    const rows = [...localPaymentHistory, ...orderPaymentHistory, ...financeInvoicePaymentHistory];
    const seen = new Set<string>();
    return rows
      .filter((row) => {
        const key = row.id > 0 ? `payment-${row.id}` : row.row_key;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .sort((a, b) => new Date(b.paid_at || 0).getTime() - new Date(a.paid_at || 0).getTime());
  }, [financeInvoicePaymentHistory, localPaymentHistory, orderPaymentHistory]);
  const payableOrders = useMemo(() => orderRows.filter((order) => order.payment_status !== "paid"), [orderRows]);
  const nextPayableOrder = payableOrders[0] || null;

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

  function defaultPaymentAmount(order: CustomerOrder) {
    if (!order.invoices?.length) return Number(order.total || 0);
    const openInvoice = order.invoices.find((invoice) => Number(invoice.balance_due || 0) > 0);
    if (openInvoice) return Number(openInvoice.balance_due || 0);
    return effectiveBalanceDue(order);
  }

  function openPayment(order: CustomerOrder) {
    setPayingOrder(order);
    setPaymentForm({
      amount: defaultPaymentAmount(order),
      date: new Date().toISOString().slice(0, 10),
      payment_method: "bank_transfer",
      notes: "",
    });
    setPaymentMsg("");
  }

  async function recordPayment(e: React.FormEvent) {
    e.preventDefault();
    if (!payingOrder) return;
    if (!Number.isFinite(Number(paymentForm.amount)) || Number(paymentForm.amount) <= 0) {
      setPaymentMsg("Amount must be greater than zero.");
      return;
    }

    setSavingPayment(true);
    setPaymentMsg("");
    try {
      const openInvoice = payingOrder.invoices?.find((invoice) => Number(invoice.balance_due || 0) > 0);
      const fallbackInvoice = payingOrder.invoices?.[0];
      const invoice = openInvoice || fallbackInvoice || await api.post<InvoiceRow>("/api/finance/invoices", {
        sales_order_id: payingOrder.id,
      });
      const paidAt = new Date(paymentForm.date).toISOString();
      const savedPayment = await api.post<PaymentRow>("/api/finance/payments", {
        invoice_id: Number(invoice.id),
        amount: Number(paymentForm.amount || 0),
        paid_at: paidAt,
        payment_method: paymentForm.payment_method,
        notes: paymentForm.notes || null,
      });
      const optimisticPayment: PaymentHistoryRow = {
        id: Number(savedPayment.id || Date.now()),
        row_key: `payment-${savedPayment.id || Date.now()}`,
        amount: Number(savedPayment.amount || paymentForm.amount || 0),
        payment_method: savedPayment.payment_method || paymentForm.payment_method,
        paid_at: savedPayment.paid_at || paidAt,
        notes: savedPayment.notes || paymentForm.notes || null,
        order_id: payingOrder.id,
        order_no: payingOrder.order_no,
        invoice_no: invoice.invoice_no || `#${invoice.id}`,
      };
      setLocalPaymentHistory((prev) => [optimisticPayment, ...prev.filter((row) => row.row_key !== optimisticPayment.row_key)]);
      setPayingOrder(null);
      void mutateOrders();
      void mutateFinanceInvoices();
    } catch (err: any) {
      setPaymentMsg(err.message || "Could not record payment.");
    } finally {
      setSavingPayment(false);
    }
  }

  if (!customer) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader title={customer.name} subtitle="Client profile with order history and payment status" />
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

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <div className="card p-4">
              <div className="label">Orders</div>
              <div className="text-2xl font-semibold">{summary.orders}</div>
              <div className="mt-1 text-xs text-slate-500">{summary.paidOrders} paid, {summary.openOrders} open</div>
            </div>
            <div className="card p-4">
              <div className="label">Order value</div>
              <div className="text-2xl font-semibold">{money(summary.orderTotal)}</div>
            </div>
            <div className="card p-4">
              <div className="label">Paid</div>
              <div className="text-2xl font-semibold text-green-700">{money(summary.paid)}</div>
            </div>
            <div className="card p-4">
              <div className="label">Open balance</div>
              <div className="text-2xl font-semibold text-red-700">{money(summary.balance)}</div>
              {summary.noInvoiceOrders > 0 && <div className="mt-1 text-xs text-slate-500">{summary.noInvoiceOrders} without invoice</div>}
            </div>
          </div>

          <section className="card overflow-x-auto">
            <div className="border-b border-[#ecebe3] px-4 py-3">
              <h2 className="app-card-title">Order history and payments</h2>
            </div>
            <table className="table min-w-[980px]">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th>
                  <th>Date</th>
                  <th>{t("field.status")}</th>
                  <th className="text-right">{t("field.total")}</th>
                  <th>Invoices</th>
                  <th className="text-right">Paid</th>
                  <th className="text-right">Balance</th>
                  <th>Payment</th>
                </tr>
              </thead>
              <tbody>
                {orderRows.map((o) => (
                  <tr key={o.id}>
                    <td><Link className="text-brand-600 hover:underline" href={`/sales-orders/${o.id}`}>{o.order_no}</Link></td>
                    <td>{o.date ? new Date(o.date).toLocaleDateString() : "-"}</td>
                    <td><span className="badge">{statusLabel(o.status, t)}</span></td>
                    <td className="text-right">{money(Number(o.total || 0))}</td>
                    <td>
                      {(o.invoices || []).length > 0 ? (
                        <div className="space-y-1">
                          {o.invoices.map((invoice) => (
                            <div key={invoice.id} className="text-xs text-slate-600">
                              <span className="font-medium text-[#14110b]">{invoice.invoice_no}</span>
                              <span> - {money(Number(invoice.amount || 0))}</span>
                              <span className="ml-1 text-slate-500">
                                paid {money(Number(invoice.paid_amount || 0))}
                                {Number(invoice.balance_due || 0) > 0 ? `, due ${money(Number(invoice.balance_due || 0))}` : ""}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500">No invoice</span>
                      )}
                    </td>
                    <td className="text-right">{money(Number(o.paid_total || 0))}</td>
                    <td className="text-right">{money(effectiveBalanceDue(o))}</td>
                    <td>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`badge ${paymentStatusClass(o.payment_status)}`}>{paymentStatusLabel(o.payment_status)}</span>
                        {o.payment_status !== "paid" && (
                          <button type="button" className="btn h-7 px-2 text-[11px]" onClick={() => openPayment(o)}>
                            <Plus className="h-3.5 w-3.5" />
                            Add payment
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {orders && orders.length === 0 && <tr><td colSpan={8} className="text-sm text-slate-500">No sales orders linked to this customer.</td></tr>}
              </tbody>
            </table>
          </section>

          <section className="card overflow-x-auto">
            <div className="flex items-center justify-between gap-3 border-b border-[#ecebe3] px-4 py-3">
              <h2 className="app-card-title">Payment history</h2>
              <button
                type="button"
                className="btn h-7 px-2 text-[11px]"
                onClick={() => nextPayableOrder && openPayment(nextPayableOrder)}
                disabled={!nextPayableOrder}
              >
                <Plus className="h-3.5 w-3.5" />
                Add payment
              </button>
            </div>
            <table className="table min-w-[760px]">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>{t("field.orderNo")}</th>
                  <th>Invoice</th>
                  <th>Method</th>
                  <th className="text-right">Amount</th>
                </tr>
              </thead>
              <tbody>
                {paymentHistory.map((payment) => (
                  <tr key={payment.id}>
                    <td>{payment.paid_at ? new Date(payment.paid_at).toLocaleDateString() : "-"}</td>
                    <td><Link className="text-brand-600 hover:underline" href={`/sales-orders/${payment.order_id}`}>{payment.order_no}</Link></td>
                    <td>{payment.invoice_no}</td>
                    <td>{payment.payment_method || "-"}</td>
                    <td className="text-right">{money(Number(payment.amount || 0))}</td>
                  </tr>
                ))}
                {orders && paymentHistory.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500">
                        <span>No payments recorded for this customer yet.</span>
                        {nextPayableOrder && (
                          <button type="button" className="btn h-7 px-2 text-[11px]" onClick={() => openPayment(nextPayableOrder)}>
                            <Plus className="h-3.5 w-3.5" />
                            Add payment
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        </div>
      </div>

      <Modal open={!!payingOrder} onClose={() => setPayingOrder(null)} title="Add payment">
        <form onSubmit={recordPayment} className="space-y-3">
          <div className="rounded-md border border-[#ecebe3] bg-[#f8f7f3] p-3 text-sm">
            <div className="font-medium">{payingOrder?.order_no || "-"}</div>
            <div className="mt-1 text-slate-600">
              {payingOrder?.invoices?.length
                ? `Open balance: ${money(effectiveBalanceDue(payingOrder))}`
                : `No invoice yet. An invoice for ${money(Number(payingOrder?.total || 0))} will be created first.`}
            </div>
          </div>
          <div>
            <label className="label">Amount received</label>
            <input
              className="input"
              type="number"
              min="0.01"
              step="0.01"
              value={paymentForm.amount}
              onChange={(e) => setPaymentForm({ ...paymentForm, amount: Number(e.target.value) })}
              required
            />
          </div>
          <div>
            <label className="label">Date</label>
            <input
              className="input"
              type="date"
              value={paymentForm.date}
              onChange={(e) => setPaymentForm({ ...paymentForm, date: e.target.value })}
              required
            />
          </div>
          <div>
            <label className="label">Payment method</label>
            <select className="input" value={paymentForm.payment_method} onChange={(e) => setPaymentForm({ ...paymentForm, payment_method: e.target.value })}>
              <option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option>
              <option value="card">Card</option>
            </select>
          </div>
          <div>
            <label className="label">Notes</label>
            <textarea
              className="input"
              rows={3}
              value={paymentForm.notes}
              onChange={(e) => setPaymentForm({ ...paymentForm, notes: e.target.value })}
            />
          </div>
          {paymentMsg && <div className="text-sm text-red-600">{paymentMsg}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => setPayingOrder(null)} disabled={savingPayment}>Cancel</button>
            <button className="btn btn-primary" disabled={savingPayment}>{savingPayment ? "Saving..." : "Save payment"}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
