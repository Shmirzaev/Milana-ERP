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
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

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
  order_id?: number | null;
  order_no?: string | null;
  invoice_id?: number | null;
  invoice_no?: string | null;
  invoice_amount?: number;
  is_advance?: boolean;
};
type InvoiceRow = {
  id: number;
  invoice_no: string;
  amount: number;
  status: string;
  issued_at?: string | null;
  due_date?: string | null;
  paid_amount: number;
  raw_paid_amount?: number;
  advance_amount?: number;
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
  amount: NumberInputValue;
  date: string;
  payment_method: string;
  notes: string;
};

function money(value: number) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function paymentStatusLabel(status: PaymentStatus, t: (key: string) => string) {
  if (status === "paid") return t("payment.status.paid");
  if (status === "partial") return t("payment.status.partial");
  if (status === "unpaid") return t("payment.status.unpaid");
  return t("payment.status.noInvoice");
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
  const { data: customerPayments, mutate: mutateCustomerPayments } = useSWR<PaymentHistoryRow[]>(`/api/customers/${id}/payments`, fetcher);
  const [form, setForm] = useState({ name: "", phone: "", email: "", address: "", notes: "" });
  const [msg, setMsg] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [paymentOpen, setPaymentOpen] = useState(false);
  const [selectedPaymentOrderId, setSelectedPaymentOrderId] = useState<number | "">("");
  const [paymentForm, setPaymentForm] = useState<PaymentForm>({
    amount: "",
    date: new Date().toISOString().slice(0, 10),
    payment_method: "bank_transfer",
    notes: "",
  });
  const [paymentMsg, setPaymentMsg] = useState("");
  const [savingPayment, setSavingPayment] = useState(false);
  const [localPaymentHistory, setLocalPaymentHistory] = useState<PaymentHistoryRow[]>([]);
  const orderRows = useMemo(() => orders || [], [orders]);

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

  const paymentHistory = useMemo<PaymentHistoryRow[]>(() => {
    const rows = [...localPaymentHistory, ...(customerPayments || []), ...orderPaymentHistory];
    const seen = new Set<string>();
    return rows
      .filter((row) => {
        const key = row.id > 0 ? `payment-${row.id}` : row.row_key;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .sort((a, b) => new Date(b.paid_at || 0).getTime() - new Date(a.paid_at || 0).getTime());
  }, [customerPayments, localPaymentHistory, orderPaymentHistory]);
  const summary = useMemo(() => {
    const base = orderRows.reduce(
      (acc, order) => {
        acc.orders += 1;
        acc.orderTotal += Number(order.total || 0);
        acc.invoiced += Number(order.invoice_total || 0);
        acc.appliedPaid += Number(order.paid_total || 0);
        acc.orderBalance += effectiveBalanceDue(order);
        if (order.payment_status === "paid") acc.paidOrders += 1;
        if (effectiveBalanceDue(order) > 0.01) acc.openOrders += 1;
        if (order.payment_status === "no_invoice") acc.noInvoiceOrders += 1;
        return acc;
      },
      {
        orders: 0,
        orderTotal: 0,
        invoiced: 0,
        appliedPaid: 0,
        orderBalance: 0,
        paidOrders: 0,
        openOrders: 0,
        noInvoiceOrders: 0,
      },
    );
    const paid = paymentHistory.reduce((sum, row) => sum + Number(row.amount || 0), 0);
    const dueBalance = Math.max(base.orderTotal - paid, 0);
    const advanceCredit = Math.max(paid - base.orderTotal, 0);
    return {
      ...base,
      paid,
      balance: dueBalance > 0 ? dueBalance : advanceCredit,
      dueBalance,
      advanceCredit,
      balanceKind: advanceCredit > 0 ? "advance" : dueBalance > 0 ? "due" : "settled",
    };
  }, [orderRows, paymentHistory]);
  const payableOrders = useMemo(() => orderRows, [orderRows]);
  const selectedPaymentOrder = useMemo(
    () => orderRows.find((order) => Number(order.id) === Number(selectedPaymentOrderId)) || null,
    [orderRows, selectedPaymentOrderId],
  );

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
    if (!form.name.trim()) next.name = t("page.profile.nameRequired");
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) next.email = t("page.profile.validEmail");
    setErrors(next);
    if (Object.keys(next).length) return;
    try {
      await api.patch(`/api/customers/${id}`, form);
      setMsg(t("msg.saved"));
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

  function paymentOrderOptionLabel(order: CustomerOrder) {
    const due = effectiveBalanceDue(order);
    return due > 0.01
      ? t("page.customerDetail.orderOptionDue", { orderNo: order.order_no, amount: money(due) })
      : t("page.customerDetail.orderOptionPaidAdvance", { orderNo: order.order_no });
  }

  function openPayment(order?: CustomerOrder) {
    setPaymentOpen(true);
    setSelectedPaymentOrderId(order?.id ?? "");
    setPaymentForm({
      amount: order ? defaultPaymentAmount(order) : "",
      date: new Date().toISOString().slice(0, 10),
      payment_method: "bank_transfer",
      notes: "",
    });
    setPaymentMsg("");
  }

  function selectPaymentOrder(rawId: string) {
    const nextId = rawId ? Number(rawId) : "";
    const order = orderRows.find((row) => Number(row.id) === Number(nextId));
    setSelectedPaymentOrderId(nextId);
    setPaymentForm((prev) => ({ ...prev, amount: order ? defaultPaymentAmount(order) : "" }));
    setPaymentMsg("");
  }

  function applyOptimisticPayment(order: CustomerOrder, invoice: InvoiceRow, payment: PaymentRow): CustomerOrder {
    const paidAmount = Number(payment.amount || 0);
    const invoiceAmount = Number(invoice.amount || order.total || 0);
    const rawPaidAmount = Number(invoice.raw_paid_amount || invoice.paid_amount || 0) + paidAmount;
    const appliedPaidAmount = Math.min(rawPaidAmount, invoiceAmount);
    const existingInvoices = order.invoices || [];
    const foundInvoice = existingInvoices.some((row) => Number(row.id) === Number(invoice.id));
    const updatedInvoice: InvoiceRow = {
      ...invoice,
      amount: invoiceAmount,
      status: Math.max(invoiceAmount - appliedPaidAmount, 0) <= 0.01 ? "paid" : "partially_paid",
      paid_amount: appliedPaidAmount,
      raw_paid_amount: rawPaidAmount,
      advance_amount: Math.max(rawPaidAmount - invoiceAmount, 0),
      balance_due: Math.max(invoiceAmount - appliedPaidAmount, 0),
      payments: [...(invoice.payments || []), payment],
    };
    const nextInvoices = foundInvoice
      ? existingInvoices.map((row) => (Number(row.id) === Number(invoice.id) ? updatedInvoice : row))
      : [...existingInvoices, updatedInvoice];
    const invoiceTotal = nextInvoices.reduce((sum, row) => sum + Number(row.amount || 0), 0);
    const paidTotal = nextInvoices.reduce((sum, row) => sum + Number(row.paid_amount || 0), 0);
    const balanceDue = Math.max(invoiceTotal - paidTotal, 0);

    return {
      ...order,
      invoices: nextInvoices,
      invoice_total: invoiceTotal,
      paid_total: paidTotal,
      balance_due: balanceDue,
      payment_status: balanceDue <= 0.01 ? "paid" : paidTotal > 0 ? "partial" : "unpaid",
      last_payment_at: payment.paid_at || order.last_payment_at,
    };
  }

  async function recordPayment(e: React.FormEvent) {
    e.preventDefault();
    const targetOrder = selectedPaymentOrder;
    const amount = numberOrZero(paymentForm.amount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setPaymentMsg(t("page.customerDetail.amountGreaterThanZero"));
      return;
    }

    setSavingPayment(true);
    setPaymentMsg("");
    try {
      const paidAt = new Date(paymentForm.date).toISOString();
      const payload: Record<string, any> = {
        amount,
        paid_at: paidAt,
        payment_method: paymentForm.payment_method,
        notes: paymentForm.notes || null,
      };
      if (targetOrder) payload.sales_order_id = Number(targetOrder.id);
      const savedPayment = await api.post<PaymentHistoryRow>(`/api/customers/${id}/payments`, {
        ...payload,
      });
      const optimisticPayment: PaymentHistoryRow = {
        ...savedPayment,
        id: Number(savedPayment.id),
        row_key: savedPayment.row_key || `payment-${savedPayment.id}`,
        amount: Number(savedPayment.amount || amount || 0),
        payment_method: savedPayment.payment_method || paymentForm.payment_method,
        paid_at: savedPayment.paid_at || paidAt,
        notes: savedPayment.notes || paymentForm.notes || null,
        order_id: savedPayment.order_id ?? null,
        order_no: savedPayment.order_no ?? null,
        invoice_id: savedPayment.invoice_id ?? null,
        invoice_no: savedPayment.invoice_no ?? null,
      };
      setLocalPaymentHistory((prev) => [optimisticPayment, ...prev.filter((row) => row.row_key !== optimisticPayment.row_key)]);
      if (targetOrder && savedPayment.invoice_id) {
        const matchingInvoice = targetOrder.invoices?.find((invoice) => Number(invoice.id) === Number(savedPayment.invoice_id));
        const invoice: InvoiceRow = matchingInvoice || {
          id: Number(savedPayment.invoice_id || 0),
          invoice_no: savedPayment.invoice_no || `#${savedPayment.invoice_id}`,
          amount: Number(savedPayment.invoice_amount || targetOrder.total || 0),
          status: "unpaid",
          issued_at: null,
          due_date: null,
          paid_amount: 0,
          balance_due: Number(savedPayment.invoice_amount || targetOrder.total || 0),
          payments: [],
        };
        const optimisticPaymentRow: PaymentRow = {
          id: optimisticPayment.id,
          amount: optimisticPayment.amount,
          payment_method: optimisticPayment.payment_method,
          paid_at: optimisticPayment.paid_at,
          notes: optimisticPayment.notes,
        };
        const nextOrders = orderRows.map((order) => (
          Number(order.id) === Number(targetOrder.id)
            ? applyOptimisticPayment(order, invoice, optimisticPaymentRow)
            : order
        ));
        mutateOrders(nextOrders, { revalidate: false });
      }
      setPaymentOpen(false);
      setSelectedPaymentOrderId("");
      void mutateCustomerPayments();
      void mutateOrders();
    } catch (err: any) {
      setPaymentMsg(err.message || t("page.customerDetail.couldNotRecordPayment"));
    } finally {
      setSavingPayment(false);
    }
  }

  if (!customer) return <div>{t("common.loading")}</div>;

  return (
    <div>
      <PageHeader title={customer.name} subtitle={t("page.customerDetail.subtitle")} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[420px_1fr]">
        <form onSubmit={save} className="card p-4 space-y-3">
          <div><label className="label">{t("common.name")}</label><input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          {errors.name && <div className="text-xs text-red-600">{errors.name}</div>}
          <div><label className="label">{t("field.phone")}</label><input className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></div>
          <div><label className="label">{t("field.email")}</label><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          {errors.email && <div className="text-xs text-red-600">{errors.email}</div>}
          <div><label className="label">{t("field.address")}</label><input className="input" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></div>
          <div><label className="label">{t("field.notes")}</label><textarea className="input min-h-24" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
          {msg && <div className={`text-sm ${msg === t("msg.saved") ? "text-green-700" : "text-red-600"}`}>{msg}</div>}
          <div className="flex justify-end"><button className="btn btn-primary">{t("btn.save")}</button></div>
        </form>

        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
            <div className="card p-4">
              <div className="label">{t("page.customerDetail.orders")}</div>
              <div className="text-2xl font-semibold">{summary.orders}</div>
              <div className="mt-1 text-xs text-slate-500">{t("page.customerDetail.paidOpen", { paid: summary.paidOrders, open: summary.openOrders })}</div>
            </div>
            <div className="card p-4">
              <div className="label">{t("field.orderValue")}</div>
              <div className="text-2xl font-semibold">{money(summary.orderTotal)}</div>
            </div>
            <div className="card p-4">
              <div className="label">{t("payment.status.paid")}</div>
              <div className="text-2xl font-semibold text-green-700">{money(summary.paid)}</div>
            </div>
            <div className="card p-4">
              <div className="label">{t("page.customerDetail.openBalance")}</div>
              <div className={`text-2xl font-semibold ${summary.balanceKind === "advance" ? "text-green-700" : summary.balanceKind === "settled" ? "text-slate-700" : "text-red-700"}`}>
                {money(summary.balance)}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {summary.balanceKind === "advance"
                  ? t("page.customerDetail.advanceCredit")
                  : summary.balanceKind === "settled"
                    ? t("page.customerDetail.settled")
                    : t("page.customerDetail.amountDue")}
              </div>
              {summary.noInvoiceOrders > 0 && <div className="mt-1 text-xs text-slate-500">{t("page.customerDetail.withoutInvoice", { count: summary.noInvoiceOrders })}</div>}
            </div>
          </div>

          <section className="card overflow-x-auto">
            <div className="border-b border-[#ecebe3] px-4 py-3">
              <h2 className="app-card-title">{t("page.customerDetail.orderHistoryPayments")}</h2>
            </div>
            <table className="table min-w-[980px]">
              <thead>
                <tr>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("field.date")}</th>
                  <th>{t("field.status")}</th>
                  <th className="text-right">{t("field.total")}</th>
                  <th>{t("field.invoice")}</th>
                  <th className="text-right">{t("payment.status.paid")}</th>
                  <th className="text-right">{t("field.balance")}</th>
                  <th>{t("field.payment")}</th>
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
                                {t("page.customerDetail.paidAmount", { amount: money(Number(invoice.paid_amount || 0)) })}
                                {Number(invoice.balance_due || 0) > 0 ? `, ${t("page.customerDetail.dueAmount", { amount: money(Number(invoice.balance_due || 0)) })}` : ""}
                                {Number(invoice.advance_amount || 0) > 0 ? `, ${t("page.customerDetail.advanceAmount", { amount: money(Number(invoice.advance_amount || 0)) })}` : ""}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500">{t("payment.status.noInvoice")}</span>
                      )}
                    </td>
                    <td className="text-right">{money(Number(o.paid_total || 0))}</td>
                    <td className="text-right">{money(effectiveBalanceDue(o))}</td>
                    <td>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={`badge ${paymentStatusClass(o.payment_status)}`}>{paymentStatusLabel(o.payment_status, t)}</span>
                        <button type="button" className="btn h-7 px-2 text-[11px]" onClick={() => openPayment(o)}>
                          <Plus className="h-3.5 w-3.5" />
                          {t("page.customerDetail.addPayment")}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {orders && orders.length === 0 && <tr><td colSpan={8} className="text-sm text-slate-500">{t("page.customerDetail.noSalesOrders")}</td></tr>}
              </tbody>
            </table>
          </section>

          <section className="card overflow-x-auto">
            <div className="flex items-center justify-between gap-3 border-b border-[#ecebe3] px-4 py-3">
              <h2 className="app-card-title">{t("page.customerDetail.paymentHistory")}</h2>
              <button
                type="button"
                className="btn h-7 px-2 text-[11px]"
                onClick={() => openPayment()}
              >
                <Plus className="h-3.5 w-3.5" />
                {t("page.customerDetail.addPayment")}
              </button>
            </div>
            <table className="table min-w-[760px]">
              <thead>
                <tr>
                  <th>{t("field.date")}</th>
                  <th>{t("field.orderNo")}</th>
                  <th>{t("field.invoice")}</th>
                  <th>{t("field.paymentMethod")}</th>
                  <th className="text-right">{t("field.amount")}</th>
                </tr>
              </thead>
              <tbody>
                {paymentHistory.map((payment) => (
                  <tr key={payment.row_key}>
                    <td>{payment.paid_at ? new Date(payment.paid_at).toLocaleDateString() : "-"}</td>
                    <td>
                      {payment.order_id ? (
                        <Link className="text-brand-600 hover:underline" href={`/sales-orders/${payment.order_id}`}>{payment.order_no}</Link>
                      ) : (
                        <span className="text-slate-500">{t("page.customerDetail.advance")}</span>
                      )}
                    </td>
                    <td>{payment.invoice_no || (payment.is_advance ? t("page.customerDetail.advance") : "-")}</td>
                    <td>{payment.payment_method || "-"}</td>
                    <td className="text-right">{money(Number(payment.amount || 0))}</td>
                  </tr>
                ))}
                {orders && paymentHistory.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500">
                        <span>{t("page.customerDetail.noPayments")}</span>
                        <button type="button" className="btn h-7 px-2 text-[11px]" onClick={() => openPayment()}>
                          <Plus className="h-3.5 w-3.5" />
                          {t("page.customerDetail.addPayment")}
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>
        </div>
      </div>

      <Modal open={paymentOpen} onClose={() => setPaymentOpen(false)} title={t("page.customerDetail.addPayment")}>
        <form onSubmit={recordPayment} className="space-y-3">
          <div className="rounded-md border border-[#ecebe3] bg-[#f8f7f3] p-3 text-sm">
            <div className="font-medium">{selectedPaymentOrder?.order_no || t("page.customerDetail.advancePayment")}</div>
            <div className="mt-1 text-slate-600">
              {selectedPaymentOrder
                ? selectedPaymentOrder.invoices?.length
                  ? effectiveBalanceDue(selectedPaymentOrder) > 0.01
                    ? t("page.customerDetail.openBalanceAdvanceHelp", { amount: money(effectiveBalanceDue(selectedPaymentOrder)) })
                    : t("page.customerDetail.orderPaidAdvanceHelp")
                  : t("page.customerDetail.noInvoiceAdvanceHelp", { amount: money(Number(selectedPaymentOrder.total || 0)) })
                : t("page.customerDetail.noOrderAdvanceHelp")}
            </div>
          </div>
          <div>
            <label className="label">{t("field.order")}</label>
            <select className="input" value={selectedPaymentOrderId} onChange={(e) => selectPaymentOrder(e.target.value)}>
              <option value="">{t("page.customerDetail.noOrderAdvanceCredit")}</option>
              {payableOrders.map((order) => (
                <option key={order.id} value={order.id}>
                  {paymentOrderOptionLabel(order)}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">{t("field.amountReceived")}</label>
            <input
              className="input"
              type="number"
              min="0.01"
              step="0.01"
              value={paymentForm.amount}
              onChange={(e) => setPaymentForm({ ...paymentForm, amount: parseNumberInput(e.target.value) })}
              required
            />
          </div>
          <div>
            <label className="label">{t("field.date")}</label>
            <input
              className="input"
              type="date"
              value={paymentForm.date}
              onChange={(e) => setPaymentForm({ ...paymentForm, date: e.target.value })}
              required
            />
          </div>
          <div>
            <label className="label">{t("field.paymentMethod")}</label>
            <select className="input" value={paymentForm.payment_method} onChange={(e) => setPaymentForm({ ...paymentForm, payment_method: e.target.value })}>
              <option value="bank_transfer">{t("payment.method.bankTransfer")}</option>
              <option value="cash">{t("payment.method.cash")}</option>
              <option value="card">{t("payment.method.card")}</option>
            </select>
          </div>
          <div>
            <label className="label">{t("field.notes")}</label>
            <textarea
              className="input"
              rows={3}
              value={paymentForm.notes}
              onChange={(e) => setPaymentForm({ ...paymentForm, notes: e.target.value })}
            />
          </div>
          {paymentMsg && <div className="text-sm text-red-600">{paymentMsg}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => setPaymentOpen(false)} disabled={savingPayment}>{t("common.cancel")}</button>
            <button className="btn btn-primary" disabled={savingPayment}>{savingPayment ? t("common.saving") : t("page.customerDetail.savePayment")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
