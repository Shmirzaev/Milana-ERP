"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";

type ReceiveFormState = {
  item_id: number;
  batch_no: string;
  supplier_id: number;
  color: string;
  old_code: string;
  color_code: string;
  color_status: string;
  order_no: string;
  quantity: number;
  piece_count: number;
  processes: string;
  unit: string;
  cost_per_unit: number;
  warehouse_id: number;
  qc_status: string;
  return_condition?: string;
};

type StockFormProps = {
  title: string;
  subtitle?: string;
  itemLabel: string;
  submitLabel: string;
  form: ReceiveFormState;
  items?: any[];
  warehouses?: any[];
  suppliers?: any[];
  salesOrders?: any[];
  message: string;
  requireOrder?: boolean;
  showReturnCondition?: boolean;
  onChange: (form: ReceiveFormState) => void;
  onSubmit: (e: React.FormEvent) => void;
};

type AccessoryIssuePlanRow = {
  item_id: number;
  item_sku: string;
  item_name: string;
  category: string;
  unit: string;
  required_quantity: number;
  issued_quantity: number;
  remaining_quantity: number;
  available_quantity: number;
  shortage: number;
};

type AccessoryIssuePlan = {
  production_order_id: number;
  production_no: string;
  order_no?: string | null;
  model_id: number;
  model_code?: string | null;
  model_name?: string | null;
  planned_quantity: number;
  rows: AccessoryIssuePlanRow[];
};

const DEFAULT_RECEIVE_FORM: ReceiveFormState = {
  item_id: 0,
  batch_no: "",
  supplier_id: 0,
  color: "",
  old_code: "",
  color_code: "",
  color_status: "",
  order_no: "",
  quantity: 0,
  piece_count: 0,
  processes: "",
  unit: "kg",
  cost_per_unit: 0,
  warehouse_id: 0,
  qc_status: "passed",
};

const DEFAULT_ACCESSORY_RETURN_FORM: ReceiveFormState = {
  ...DEFAULT_RECEIVE_FORM,
  processes: "Collected back accessories",
  return_condition: "used",
  unit: "pcs",
};

function toReceivePayload(form: ReceiveFormState) {
  const { return_condition, ...stockFields } = form;
  const processNote = stockFields.processes.trim();
  const returnConditionNote = return_condition ? `Accessory condition: ${return_condition}` : "";
  const processes = [returnConditionNote, processNote].filter(Boolean).join("; ");

  return {
    ...stockFields,
    supplier_id: form.supplier_id || null,
    old_code: form.old_code.trim() || null,
    color_code: form.color_code.trim() || null,
    color_status: form.color_status.trim() || null,
    order_no: form.order_no.trim() || null,
    piece_count: form.piece_count > 0 ? form.piece_count : null,
    processes: processes || null,
  };
}

function StockForm({
  title,
  subtitle,
  itemLabel,
  submitLabel,
  form,
  items,
  warehouses,
  suppliers,
  salesOrders,
  message,
  requireOrder = false,
  showReturnCondition = false,
  onChange,
  onSubmit,
}: StockFormProps) {
  const { t } = useT();
  const spanClass = "md:col-span-2";

  return (
    <form onSubmit={onSubmit} className="card grid grid-cols-1 gap-3 p-6 md:grid-cols-2">
      <div className={spanClass}>
        <div className="text-base font-semibold text-[#14110b]">{title}</div>
        {subtitle && <div className="mt-1 text-sm text-[#6f684f]">{subtitle}</div>}
      </div>

      <div>
        <label className="label">{itemLabel}</label>
        <select className="input" value={form.item_id} onChange={(e) => onChange({ ...form, item_id: Number(e.target.value) })} required>
          <option value={0}>{itemLabel}</option>
          {items?.map((i) => <option key={i.id} value={i.id}>{i.sku} - {i.name}</option>)}
        </select>
      </div>
      <div>
        <label className="label">{t("field.batch")}</label>
        <input className="input" placeholder={t("field.batch")} value={form.batch_no} onChange={(e) => onChange({ ...form, batch_no: e.target.value })} required />
      </div>
      <div>
        <label className="label">{t("field.materialColor")}</label>
        <input className="input" placeholder={t("field.materialColor")} value={form.color} onChange={(e) => onChange({ ...form, color: e.target.value })} />
      </div>
      <div>
        <label className="label">{t("field.oldCode")}</label>
        <input className="input" placeholder={t("field.oldCode")} value={form.old_code} onChange={(e) => onChange({ ...form, old_code: e.target.value })} />
      </div>
      <div>
        <label className="label">{t("field.colorCode")}</label>
        <input className="input" placeholder={t("field.colorCode")} value={form.color_code} onChange={(e) => onChange({ ...form, color_code: e.target.value })} />
      </div>
      <div>
        <label className="label">{t("field.colorStatus")}</label>
        <input className="input" placeholder={t("field.colorStatus")} value={form.color_status} onChange={(e) => onChange({ ...form, color_status: e.target.value })} />
      </div>

      <div>
        <label className="label">{t("field.orderNo")}</label>
        {salesOrders ? (
          <select className="input" value={form.order_no} onChange={(e) => onChange({ ...form, order_no: e.target.value })} required={requireOrder}>
            <option value="">{t("ph.orderNo")}</option>
            {salesOrders.map((o) => <option key={o.id} value={o.order_no}>{o.order_no} - {o.customer_name || o.customer_id || "-"}</option>)}
          </select>
        ) : (
          <input className="input" placeholder={t("field.orderNo")} value={form.order_no} onChange={(e) => onChange({ ...form, order_no: e.target.value })} required={requireOrder} />
        )}
      </div>
      {showReturnCondition && (
        <div>
          <label className="label">{t("field.accessoryCondition")}</label>
          <select className="input" value={form.return_condition || "used"} onChange={(e) => onChange({ ...form, return_condition: e.target.value })} required>
            <option value="new">{t("accessoryCondition.new")}</option>
            <option value="used">{t("accessoryCondition.used")}</option>
          </select>
        </div>
      )}
      <div>
        <label className="label">{t("field.netto")}</label>
        <input className="input" type="number" step="0.01" placeholder={t("field.netto")} value={form.quantity} onChange={(e) => onChange({ ...form, quantity: Number(e.target.value) })} required />
      </div>
      <div>
        <label className="label">{t("field.pieceCount")}</label>
        <input className="input" type="number" min={0} placeholder={t("field.pieceCount")} value={form.piece_count} onChange={(e) => onChange({ ...form, piece_count: Number(e.target.value) })} />
      </div>
      <div>
        <label className="label">{t("ph.supplier")}</label>
        <select className="input" value={form.supplier_id} onChange={(e) => onChange({ ...form, supplier_id: Number(e.target.value) })}>
          <option value={0}>{t("ph.supplier")}</option>
          {suppliers?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>

      <div className={spanClass}>
        <label className="label">{t("field.processes")}</label>
        <input className="input" placeholder={t("field.processes")} value={form.processes} onChange={(e) => onChange({ ...form, processes: e.target.value })} />
      </div>

      <div>
        <label className="label">{t("field.unit")}</label>
        <input className="input" placeholder={t("field.unit")} value={form.unit} onChange={(e) => onChange({ ...form, unit: e.target.value })} />
      </div>
      <div>
        <label className="label">{`${t("field.cost")} / ${t("field.unit")}`}</label>
        <input className="input" type="number" step="0.01" placeholder={t("field.cost") + " / " + t("field.unit")} value={form.cost_per_unit} onChange={(e) => onChange({ ...form, cost_per_unit: Number(e.target.value) })} />
      </div>

      <div>
        <label className="label">{t("ph.warehouse")}</label>
        <select className="input" value={form.warehouse_id} onChange={(e) => onChange({ ...form, warehouse_id: Number(e.target.value) })} required>
          <option value={0}>{t("ph.warehouse")}</option>
          {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
      </div>
      <div>
        <label className="label">{t("page.receiveStock.qcStatus")}</label>
        <select className="input" value={form.qc_status} onChange={(e) => onChange({ ...form, qc_status: e.target.value })}>
          <option value="pending">{t("qc.pending")}</option>
          <option value="passed">{t("qc.passed")}</option>
          <option value="failed">{t("qc.failed")}</option>
        </select>
      </div>

      <button className={`btn btn-primary ${spanClass}`}>{submitLabel}</button>
      {message && <div className={`text-sm ${spanClass}`}>{message}</div>}
    </form>
  );
}

function fmtQty(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

export default function ReceiveStockPage() {
  const { t } = useT();
  const { data: materialItems } = useSWR<any[]>("/api/inventory/items?group=materials", fetcher);
  const { data: accessoryItems } = useSWR<any[]>("/api/inventory/items?group=accessories", fetcher);
  const { data: warehouses } = useSWR<any[]>("/api/inventory/warehouses", fetcher);
  const { data: suppliers } = useSWR<any[]>("/api/suppliers", fetcher);
  const { data: salesOrders } = useSWR<any[]>("/api/sales-orders?page_size=500", fetcher);
  const { data: productionOrders } = useSWR<any[]>("/api/production-orders?page_size=500", fetcher);
  const { data: models } = useSWR<any[]>("/api/models", fetcher);
  const { data: batches, mutate: refreshBatches } = useSWR<any[]>("/api/inventory/batches", fetcher);
  const [receiveForm, setReceiveForm] = useState(DEFAULT_RECEIVE_FORM);
  const [accessoryReturnForm, setAccessoryReturnForm] = useState(DEFAULT_ACCESSORY_RETURN_FORM);
  const [issueProductionOrderId, setIssueProductionOrderId] = useState(0);
  const [issueQuantities, setIssueQuantities] = useState<Record<number, string>>({});
  const [receiveMsg, setReceiveMsg] = useState("");
  const [accessoryMsg, setAccessoryMsg] = useState("");
  const [issueMsg, setIssueMsg] = useState("");
  const [issueBusy, setIssueBusy] = useState(false);
  const { data: issuePlan, mutate: refreshIssuePlan } = useSWR<AccessoryIssuePlan>(
    issueProductionOrderId ? `/api/inventory/accessory-issue-plan?production_order_id=${issueProductionOrderId}` : null,
    fetcher,
  );
  const modelById = useMemo(() => new Map((models || []).map((m) => [Number(m.id), m])), [models]);

  useEffect(() => {
    if (!issuePlan?.rows) {
      setIssueQuantities({});
      return;
    }
    const next: Record<number, string> = {};
    for (const row of issuePlan.rows) {
      const suggested = Math.min(Number(row.remaining_quantity || 0), Number(row.available_quantity || 0));
      next[row.item_id] = suggested > 0 ? String(Number(suggested.toFixed(4))) : "";
    }
    setIssueQuantities(next);
  }, [issuePlan]);

  async function submitReceive(e: React.FormEvent) {
    e.preventDefault();
    setReceiveMsg("");
    try {
      await api.post("/api/inventory/receive", toReceivePayload(receiveForm));
      setReceiveMsg(t("msg.recorded"));
      setReceiveForm(DEFAULT_RECEIVE_FORM);
      refreshBatches();
    } catch (e: any) {
      setReceiveMsg(e.message);
    }
  }

  async function submitAccessoryReturn(e: React.FormEvent) {
    e.preventDefault();
    setAccessoryMsg("");
    try {
      await api.post("/api/inventory/receive", toReceivePayload(accessoryReturnForm));
      setAccessoryMsg(t("msg.recorded"));
      setAccessoryReturnForm(DEFAULT_ACCESSORY_RETURN_FORM);
      refreshBatches();
    } catch (e: any) {
      setAccessoryMsg(e.message);
    }
  }

  async function submitAccessoryIssue(e: React.FormEvent) {
    e.preventDefault();
    setIssueMsg("");
    if (!issueProductionOrderId || !issuePlan) {
      setIssueMsg(t("page.receiveStock.selectPoFirst"));
      return;
    }
    const lines = issuePlan.rows
      .map((row) => ({
        item_id: row.item_id,
        quantity: Number(issueQuantities[row.item_id] || 0),
        unit: row.unit,
      }))
      .filter((line) => Number.isFinite(line.quantity) && line.quantity > 0);
    if (!lines.length) {
      setIssueMsg(t("page.receiveStock.noIssueQty"));
      return;
    }
    setIssueBusy(true);
    try {
      await api.post("/api/inventory/accessory-issues", {
        production_order_id: issueProductionOrderId,
        lines,
      });
      setIssueMsg(t("msg.recorded"));
      refreshIssuePlan();
      refreshBatches();
    } catch (e: any) {
      setIssueMsg(e.message);
    } finally {
      setIssueBusy(false);
    }
  }

  const selectedPo = productionOrders?.find((po) => Number(po.id) === Number(issueProductionOrderId));
  const selectedPoModel = selectedPo ? modelById.get(Number(selectedPo.model_id)) : null;

  return (
    <div>
      <PageHeader title={t("page.receiveStock.title")} subtitle={t("page.receiveStock.subtitle")} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <StockForm
          title={t("page.receiveStock.materialForm")}
          itemLabel={t("field.materialName")}
          submitLabel={t("btn.receive")}
          form={receiveForm}
          items={materialItems}
          warehouses={warehouses}
          suppliers={suppliers}
          message={receiveMsg}
          onChange={setReceiveForm}
          onSubmit={submitReceive}
        />
        <StockForm
          title={t("page.receiveStock.accessoryReturnTitle")}
          subtitle={t("page.receiveStock.accessoryReturnSubtitle")}
          itemLabel={t("field.accessory")}
          submitLabel={t("btn.collectBack")}
          form={accessoryReturnForm}
          items={accessoryItems}
          warehouses={warehouses}
          suppliers={suppliers}
          salesOrders={salesOrders}
          message={accessoryMsg}
          requireOrder
          showReturnCondition
          onChange={setAccessoryReturnForm}
          onSubmit={submitAccessoryReturn}
        />
      </div>

      <form onSubmit={submitAccessoryIssue} className="card mt-4 overflow-hidden">
        <div className="border-b border-[#ecebe3] p-6">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(260px,380px)] lg:items-end">
            <div>
              <div className="text-base font-semibold text-[#14110b]">{t("page.receiveStock.accessoryIssueTitle")}</div>
              <div className="mt-1 text-sm text-[#6f684f]">{t("page.receiveStock.accessoryIssueSubtitle")}</div>
            </div>
            <div>
              <label className="label">{t("field.orderNo")}</label>
              <select
                className="input"
                value={issueProductionOrderId}
                onChange={(e) => { setIssueProductionOrderId(Number(e.target.value)); setIssueMsg(""); }}
              >
                <option value={0}>{t("page.receiveStock.selectProductionOrder")}</option>
                {productionOrders?.map((po) => {
                  const model = modelById.get(Number(po.model_id));
                  const modelValue = model?.code || po.model_id;
                  const modelText = modelValue ? `Model ${modelValue}` : "";
                  const label = [
                    orderReference(po, `#${po.id}`),
                    modelText,
                  ].filter(Boolean).join(" - ");
                  return <option key={po.id} value={po.id}>{label}</option>;
                })}
              </select>
            </div>
          </div>
          {issuePlan && (
            <div className="mt-3 text-sm text-[#56503f]">
              <span className="mono font-semibold text-[#14110b]">{orderReference(issuePlan, issuePlan.production_no)}</span>
              {" · "}
              {[issuePlan.model_code || selectedPoModel?.code, issuePlan.model_name || selectedPoModel?.name].filter(Boolean).join(" - ") || `#${issuePlan.model_id}`}
              {" · "}
              {t("page.poDetail.plannedQty")}: {issuePlan.planned_quantity}
            </div>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.sku")}</th>
                <th>{t("common.name")}</th>
                <th>{t("page.receiveStock.requiredQty")}</th>
                <th>{t("page.receiveStock.issuedQty")}</th>
                <th>{t("page.receiveStock.remainingQty")}</th>
                <th>{t("page.receiveStock.availableQty")}</th>
                <th>{t("page.receiveStock.issueNow")}</th>
                <th>{t("field.unit")}</th>
              </tr>
            </thead>
            <tbody>
              {issuePlan?.rows?.map((row) => (
                <tr key={`${row.item_id}-${row.unit}`}>
                  <td className="mono">{row.item_sku}</td>
                  <td>{row.item_name}</td>
                  <td className="mono">{fmtQty(row.required_quantity)}</td>
                  <td className="mono">{fmtQty(row.issued_quantity)}</td>
                  <td className="mono font-semibold text-[#14110b]">{fmtQty(row.remaining_quantity)}</td>
                  <td className={`mono ${Number(row.shortage || 0) > 0 ? "text-red-700" : ""}`}>{fmtQty(row.available_quantity)}</td>
                  <td>
                    <input
                      className="input min-w-[112px]"
                      type="number"
                      min={0}
                      step="0.0001"
                      max={Math.min(Number(row.remaining_quantity || 0), Number(row.available_quantity || 0))}
                      value={issueQuantities[row.item_id] ?? ""}
                      onChange={(e) => setIssueQuantities({ ...issueQuantities, [row.item_id]: e.target.value })}
                    />
                  </td>
                  <td>{row.unit}</td>
                </tr>
              ))}
              {issueProductionOrderId > 0 && issuePlan?.rows?.length === 0 && (
                <tr>
                  <td colSpan={8} className="text-sm text-slate-400">{t("page.receiveStock.noAccessoryBom")}</td>
                </tr>
              )}
              {!issueProductionOrderId && (
                <tr>
                  <td colSpan={8} className="text-sm text-slate-400">{t("page.receiveStock.selectPoFirst")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="flex flex-col gap-3 border-t border-[#ecebe3] p-4 sm:flex-row sm:items-center sm:justify-end">
          {issueMsg && <div className="text-sm text-[#56503f] sm:mr-auto">{issueMsg}</div>}
          <button className="btn btn-primary" disabled={issueBusy || !issueProductionOrderId}>
            {issueBusy ? t("common.saving") : t("page.receiveStock.issueAccessories")}
          </button>
        </div>
      </form>

      <div className="card mt-4 overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.batch").toUpperCase()}</th>
              <th>{t("field.materialName").toUpperCase()}</th>
              <th>{t("field.materialColor").toUpperCase()}</th>
              <th>{t("field.oldCode").toUpperCase()}</th>
              <th>{t("field.colorCode").toUpperCase()}</th>
              <th>{t("field.colorStatus").toUpperCase()}</th>
              <th>{t("field.orderNo").toUpperCase()}</th>
              <th>{t("field.netto").toUpperCase()}</th>
              <th>{t("field.pieceCount").toUpperCase()}</th>
              <th>{t("field.processes").toUpperCase()}</th>
            </tr>
          </thead>
          <tbody>
            {batches?.slice(0, 30).map((b) => (
              <tr key={b.id}>
                <td>{b.batch_no}</td>
                <td>{b.item_name ? `${b.item_sku || ""} ${b.item_name}`.trim() : b.item_id}</td>
                <td>{b.color || "-"}</td>
                <td>{b.old_code || "-"}</td>
                <td>{b.color_code || "-"}</td>
                <td>{b.color_status || "-"}</td>
                <td>{b.order_no || "-"}</td>
                <td>{Number(b.quantity).toFixed(2)}</td>
                <td>{b.piece_count ?? "-"}</td>
                <td>{b.processes || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
