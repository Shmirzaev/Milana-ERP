"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";
import { statusLabel } from "@/components/StagePipeline";
import { useDialogs } from "@/components/DialogProvider";
import { numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";

type RevenueRow = { period: string; amount: number };
type InvoiceRow = {
  id: number;
  invoice_no?: string;
  order_no: string;
  customer?: string | null;
  amount: number;
  status: string;
  date?: string | null;
};

type CostBreakdown = {
  fabric_cost: number;
  labor_cost: number;
  accessories_cost: number;
  total_cogs: number;
};

function money(value: number) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function Card({ title, value }: { title: string; value: string }) {
  return (
    <div className="card p-5">
      <div className="text-xs text-slate-500 uppercase tracking-wide">{title}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
    </div>
  );
}

export default function FinancePage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [paying, setPaying] = useState<InvoiceRow | null>(null);
  const [payment, setPayment] = useState<{ amount: NumberInputValue; date: string; payment_method: string }>({ amount: "", date: new Date().toISOString().slice(0, 10), payment_method: "bank_transfer" });
  const [paymentMsg, setPaymentMsg] = useState("");

  const revenueUrl = useMemo(() => {
    const params = new URLSearchParams();
    if (from) params.set("from", new Date(from).toISOString());
    if (to) params.set("to", new Date(to).toISOString());
    const qs = params.toString();
    return qs ? `/api/finance/revenue-by-period?${qs}` : "/api/finance/revenue-by-period";
  }, [from, to]);

  const { data, mutate: mutateDashboard } = useSWR<any>("/api/finance/dashboard", fetcher);
  const { data: branded } = useSWR<any>("/api/finance/branded-stock-value", fetcher);
  const { data: waste } = useSWR<any>("/api/finance/waste-report", fetcher);
  const { data: invoices, mutate: mutateInvoices } = useSWR<InvoiceRow[]>("/api/finance/invoices?limit=50", fetcher);
  const { data: revenue } = useSWR<RevenueRow[]>(revenueUrl, fetcher);
  const { data: cogs } = useSWR<CostBreakdown>("/api/finance/cost-breakdown", fetcher);

  const maxRevenue = useMemo(() => {
    const values = (revenue || []).map((row) => Number(row.amount || 0));
    return Math.max(1, ...(values.length ? values : [1]));
  }, [revenue]);

  function openPayment(inv: InvoiceRow) {
    setPaying(inv);
    setPayment({ amount: Number(inv.amount || 0), date: new Date().toISOString().slice(0, 10), payment_method: "bank_transfer" });
    setPaymentMsg("");
  }

  async function recordPayment(e: React.FormEvent) {
    e.preventDefault();
    if (!paying) return;
    if (!(await dialogs.ask({ message: t("page.finance.recordPaymentConfirm", { invoice: paying.invoice_no || paying.order_no }) }))) return;
    setPaymentMsg("");
    try {
      await api.post("/api/finance/payments", {
        invoice_id: paying.id,
        amount: numberOrZero(payment.amount),
        paid_at: new Date(payment.date).toISOString(),
        payment_method: payment.payment_method,
      });
      setPaying(null);
      await mutateInvoices();
      await mutateDashboard();
    } catch (err: any) {
      setPaymentMsg(err.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.finance.title")} />
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4 lg:gap-4">
        <Card title={t("page.finance.revenue")} value={money(Number(data?.revenue_total || 0))} />
        <Card title={t("page.finance.paymentsReceived")} value={money(Number(data?.payments_received || 0))} />
        <Card title={t("page.finance.brandedValue")} value={money(Number(branded?.value || 0))} />
        <Card title={t("page.finance.wasteCostIncome")} value={`${money(Number(waste?.cost || 0))} / ${money(Number(waste?.income || 0))}`} />
      </div>

      <div className="card p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold">{t("page.finance.recentInvoices")}</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.invoiceNo")}</th>
                <th>{t("field.orderNo")}</th>
                <th>{t("field.customer")}</th>
                <th>{t("field.amount")}</th>
                <th>{t("field.status")}</th>
                <th>{t("field.date")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {(invoices || []).length === 0 && (
                <tr>
                  <td colSpan={7} className="text-sm text-slate-500">{t("page.finance.noInvoices")}</td>
                </tr>
              )}
              {(invoices || []).map((inv) => (
                <tr key={inv.id}>
                  <td>{inv.invoice_no || inv.id}</td>
                  <td>{inv.order_no}</td>
                  <td>{inv.customer || "-"}</td>
                  <td>{money(Number(inv.amount || 0))}</td>
                  <td>
                    <span className={`badge ${String(inv.status).toLowerCase() === "paid" ? "badge-green" : "badge-yellow"}`}>
                      {statusLabel(inv.status, t)}
                    </span>
                  </td>
                  <td>{inv.date ? new Date(inv.date).toLocaleDateString() : "-"}</td>
                  <td>
                    {String(inv.status).toLowerCase() !== "paid" ? (
                      <button className="btn h-7 px-2 text-[11px]" onClick={() => openPayment(inv)}>{t("page.finance.recordPayment")}</button>
                    ) : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Modal open={!!paying} onClose={() => setPaying(null)} title={t("page.finance.recordPayment")}>
        <form onSubmit={recordPayment} className="space-y-3">
          <div className="text-sm text-slate-600">
            {paying?.invoice_no || "-"} - {paying?.order_no || "-"} - {money(Number(paying?.amount || 0))}
          </div>
          <div><label className="label">{t("field.amountReceived")}</label><input className="input" type="number" step="0.01" value={payment.amount} onChange={(e) => setPayment({ ...payment, amount: parseNumberInput(e.target.value) })} required /></div>
          <div><label className="label">{t("field.date")}</label><input className="input" type="date" value={payment.date} onChange={(e) => setPayment({ ...payment, date: e.target.value })} required /></div>
          <div>
            <label className="label">{t("field.paymentMethod")}</label>
            <select className="input" value={payment.payment_method} onChange={(e) => setPayment({ ...payment, payment_method: e.target.value })}>
              <option value="bank_transfer">{t("payment.method.bankTransfer")}</option>
              <option value="cash">{t("payment.method.cash")}</option>
              <option value="card">{t("payment.method.card")}</option>
            </select>
          </div>
          {paymentMsg && <div className="text-sm text-red-600">{paymentMsg}</div>}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn" onClick={() => setPaying(null)}>{t("common.cancel")}</button>
            <button className="btn btn-primary">{t("common.save")}</button>
          </div>
        </form>
      </Modal>

      <div className="card p-4 mb-6">
        <div className="mb-3 flex flex-wrap items-end gap-3">
          <div className="font-semibold">{t("page.finance.revenueOverTime")}</div>
          <div className="ml-auto flex items-end gap-2">
            <div>
              <label className="label">{t("field.from")}</label>
              <input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div>
              <label className="label">{t("field.to")}</label>
              <input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>
        </div>
        {(revenue || []).length === 0 ? (
          <div className="text-sm text-slate-500">{t("page.finance.noRevenueData")}</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            {(revenue || []).map((row) => {
              const value = Number(row.amount || 0);
              const pct = Math.max(4, Math.round((value / maxRevenue) * 100));
              return (
                <div key={row.period} className="rounded-md border border-[#ecebe3] p-2">
                  <div className="h-28 flex items-end">
                    <div className="w-full rounded-sm bg-[#1f7a4d]" style={{ height: `${pct}%` }} />
                  </div>
                  <div className="mt-2 text-xs text-slate-500">{row.period}</div>
                  <div className="text-sm font-medium">{money(value)}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="card p-4">
        <h2 className="font-semibold mb-3">{t("page.finance.costBreakdown")}</h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div className="rounded-md border border-[#ecebe3] p-3">
            <div className="text-xs text-slate-500 uppercase">{t("page.finance.fabricCost")}</div>
            <div className="text-lg font-semibold">{money(Number(cogs?.fabric_cost || 0))}</div>
          </div>
          <div className="rounded-md border border-[#ecebe3] p-3">
            <div className="text-xs text-slate-500 uppercase">{t("page.finance.laborCost")}</div>
            <div className="text-lg font-semibold">{money(Number(cogs?.labor_cost || 0))}</div>
          </div>
          <div className="rounded-md border border-[#ecebe3] p-3">
            <div className="text-xs text-slate-500 uppercase">{t("page.finance.accessoriesCost")}</div>
            <div className="text-lg font-semibold">{money(Number(cogs?.accessories_cost || 0))}</div>
          </div>
          <div className="rounded-md border border-[#ecebe3] p-3">
            <div className="text-xs text-slate-500 uppercase">{t("page.finance.totalCogs")}</div>
            <div className="text-lg font-semibold">{money(Number(cogs?.total_cogs || 0))}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
