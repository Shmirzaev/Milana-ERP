"use client";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";
import { imagePreviewHref, storageThumbnailUrl } from "@/lib/modelImages";
import { MATERIAL_COLOR_OPTIONS, materialColorLabelKey } from "@/lib/materialColors";

type ReceiveFormState = {
  item_id: number;
  production_order_id: number;
  batch_no: string;
  supplier_id: number;
  color: string;
  old_code: string;
  color_code: string;
  color_status: string;
  order_no: string;
  quantity: number | "";
  gsm: string | number;
  piece_count: number | "";
  processes: string;
  unit: string;
  cost_per_unit: number | "";
  warehouse_id: number;
  qc_status: string;
  image_url: string;
  return_condition?: string;
};

type ReceiveItem = {
  id: number;
  name: string;
  category?: string | null;
  unit?: string | null;
};

type OrderOption = {
  id: number;
  label: string;
  orderNo: string;
};

type StockFormProps = {
  title: string;
  subtitle?: string;
  itemLabel: string;
  submitLabel: string;
  form: ReceiveFormState;
  items?: ReceiveItem[];
  warehouses?: any[];
  suppliers?: any[];
  orderOptions?: OrderOption[];
  message: string;
  requireOrder?: boolean;
  showOrder?: boolean;
  showReturnCondition?: boolean;
  showGramaj?: boolean;
  noOrderOptionsMessage?: string;
  showItemImage?: boolean;
  uploadingImage?: boolean;
  customColors: string[];
  onChange: (form: ReceiveFormState) => void;
  onAddColor: (color: string) => void;
  onUploadItemImage?: (file?: File | null) => void;
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

type AccessoryIssueSummaryRow = {
  production_order_id: number;
  production_no: string;
  order_no?: string | null;
  model_id: number;
  model_code?: string | null;
  model_name?: string | null;
  item_id: number;
  item_sku: string;
  item_name: string;
  category: string;
  unit: string;
  issued_quantity: number;
  returned_quantity?: number;
  returnable_quantity?: number;
};

const DEFAULT_RECEIVE_FORM: ReceiveFormState = {
  item_id: 0,
  production_order_id: 0,
  batch_no: "",
  supplier_id: 0,
  color: "",
  old_code: "",
  color_code: "",
  color_status: "",
  order_no: "",
  quantity: "",
  gsm: "",
  piece_count: "",
  processes: "",
  unit: "kg",
  cost_per_unit: "",
  warehouse_id: 0,
  qc_status: "passed",
  image_url: "",
};

const DEFAULT_ACCESSORY_RETURN_FORM: ReceiveFormState = {
  ...DEFAULT_RECEIVE_FORM,
  processes: "Collected back accessories",
  return_condition: "used",
  unit: "pcs",
};

function numericInputValue(value: string): number | "" {
  return value === "" ? "" : Number(value);
}

function numberOrZero(value: number | string | ""): number {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toReceivePayload(form: ReceiveFormState) {
  const processNote = form.processes.trim();
  const pieceCount = numberOrZero(form.piece_count);

  return {
    item_id: form.item_id,
    batch_no: form.batch_no,
    color: form.color,
    quantity: numberOrZero(form.quantity),
    unit: form.unit,
    cost_per_unit: numberOrZero(form.cost_per_unit),
    warehouse_id: form.warehouse_id,
    qc_status: form.qc_status,
    supplier_id: form.supplier_id || null,
    old_code: form.old_code.trim() || null,
    color_code: form.color_code.trim() || null,
    color_status: form.color_status.trim() || null,
    order_no: form.order_no.trim() || null,
    gsm: form.gsm === "" ? null : Number(form.gsm),
    piece_count: pieceCount > 0 ? pieceCount : null,
    processes: processNote || null,
    image_url: form.image_url.trim() || null,
  };
}

function materialColorLabel(value: unknown, t: (key: string) => string) {
  const rawValue = String(value || "").trim();
  if (!rawValue) return "-";
  const labelKey = materialColorLabelKey(rawValue);
  return labelKey ? t(labelKey) : rawValue;
}

function toAccessoryReturnPayload(form: ReceiveFormState) {
  return {
    ...toReceivePayload(form),
    production_order_id: form.production_order_id,
    return_condition: form.return_condition || "used",
  };
}

function isItemImageUrl(value: unknown): boolean {
  const url = String(value || "").trim();
  return url.startsWith("/storage/model-files/") || /\.(png|jpe?g|webp|gif)(?:[?#].*)?$/i.test(url);
}

function itemPicture(imageUrl: string | null | undefined, alt: string, noImage: string, preview: string) {
  const url = String(imageUrl || "").trim();
  if (!url) {
    return (
      <div className="flex h-12 w-12 items-center justify-center rounded-md border border-dashed border-[#ded9ca] bg-[#f8f6ef] text-[10px] leading-tight text-[#8a8472]">
        {noImage}
      </div>
    );
  }
  const isImage = isItemImageUrl(url);
  return (
    <a
      href={isImage ? imagePreviewHref(url, alt) : url}
      target="_blank"
      rel="noreferrer"
      className="flex h-12 w-12 items-center justify-center overflow-hidden rounded-md border border-[#ded9ca] bg-white text-[11px] text-[#8a8472]"
    >
      {isImage ? <img src={storageThumbnailUrl(url, 320)} alt={alt} className="h-full w-full object-cover" /> : preview}
    </a>
  );
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
  orderOptions,
  message,
  requireOrder = false,
  showOrder = true,
  showReturnCondition = false,
  showGramaj = false,
  noOrderOptionsMessage,
  showItemImage = false,
  uploadingImage = false,
  customColors,
  onChange,
  onAddColor,
  onUploadItemImage,
  onSubmit,
}: StockFormProps) {
  const { t } = useT();
  const [showColorInput, setShowColorInput] = useState(false);
  const [newColor, setNewColor] = useState("");
  const spanClass = "md:col-span-2";
  const selectedOrderId = Number(form.production_order_id || 0);
  const presetColorValues = new Set(MATERIAL_COLOR_OPTIONS.map((option) => option.value.toLowerCase()));
  const visibleCustomColors = customColors.filter((color) => !presetColorValues.has(color.toLowerCase()));

  function addColor() {
    const color = newColor.trim();
    if (!color) return;
    const preset = MATERIAL_COLOR_OPTIONS.find((option) => option.value.toLowerCase() === color.toLowerCase());
    const selectedColor = preset?.value || visibleCustomColors.find((option) => option.toLowerCase() === color.toLowerCase()) || color;
    onAddColor(selectedColor);
    onChange({ ...form, color: selectedColor });
    setNewColor("");
    setShowColorInput(false);
  }

  return (
    <form onSubmit={onSubmit} className="card grid grid-cols-1 gap-3 p-6 md:grid-cols-2">
      <div className={spanClass}>
        <div className="text-base font-semibold text-[#14110b]">{title}</div>
        {subtitle && <div className="mt-1 text-sm text-[#6f684f]">{subtitle}</div>}
      </div>

      <div>
        <label className="label">{itemLabel}</label>
        <select
          className="input"
          value={form.item_id}
          onChange={(e) => {
            const itemId = Number(e.target.value);
            const item = items?.find((row) => Number(row.id) === itemId);
            onChange({ ...form, item_id: itemId, unit: item?.unit || form.unit, image_url: "" });
          }}
          required
        >
          <option value={0}>{itemLabel}</option>
          {items?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </select>
      </div>
      {showItemImage && (
        <div className={spanClass}>
          <label className="label">{t("field.picture")}</label>
          <div className="rounded-md border border-[#ecebe3] bg-[#fbfaf6] p-3">
            <div className="flex items-start gap-3">
              {itemPicture(form.image_url, t("field.picture"), t("page.masterData.noImage"), t("field.preview"))}
              <div className="min-w-0 flex-1 space-y-2">
                <input
                  className="input"
                  placeholder={t("page.masterData.imageUrl")}
                  value={form.image_url}
                  disabled={!form.item_id}
                  onChange={(event) => onChange({ ...form, image_url: event.target.value })}
                />
                <label className={`btn inline-flex cursor-pointer px-3 py-2 text-sm ${uploadingImage || !form.item_id ? "pointer-events-none opacity-60" : ""}`}>
                  {uploadingImage ? t("common.uploading") : t("page.masterData.uploadImage")}
                  <input
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif"
                    className="hidden"
                    disabled={uploadingImage || !form.item_id}
                    onChange={(event) => {
                      onUploadItemImage?.(event.currentTarget.files?.[0] || null);
                      event.currentTarget.value = "";
                    }}
                  />
                </label>
              </div>
            </div>
          </div>
        </div>
      )}
      <div>
        <label className="label">{t("field.batch")}</label>
        <input className="input" placeholder={t("field.batch")} value={form.batch_no} onChange={(e) => onChange({ ...form, batch_no: e.target.value })} required />
      </div>
      <div>
        <label className="label">{t("field.materialColor")}</label>
        <div className="flex items-center gap-2">
          <select className="input min-w-0 flex-1" value={form.color} onChange={(e) => onChange({ ...form, color: e.target.value })}>
            <option value="">{t("page.receiveStock.selectMaterialColor")}</option>
            {MATERIAL_COLOR_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{t(option.labelKey)}</option>
            ))}
            {visibleCustomColors.map((color) => (
              <option key={color} value={color}>{color}</option>
            ))}
          </select>
          <button type="button" className="btn shrink-0" onClick={() => setShowColorInput(true)}>
            {t("page.receiveStock.addColor")}
          </button>
        </div>
        {showColorInput && (
          <div className="mt-2 flex items-center gap-2">
            <input
              className="input min-w-0 flex-1"
              autoFocus
              placeholder={t("page.receiveStock.colorName")}
              value={newColor}
              onChange={(event) => setNewColor(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addColor();
                }
                if (event.key === "Escape") {
                  setNewColor("");
                  setShowColorInput(false);
                }
              }}
            />
            <button type="button" className="btn btn-primary shrink-0" disabled={!newColor.trim()} onClick={addColor}>
              {t("common.add")}
            </button>
            <button
              type="button"
              className="btn shrink-0"
              onClick={() => {
                setNewColor("");
                setShowColorInput(false);
              }}
            >
              {t("common.cancel")}
            </button>
          </div>
        )}
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

      {showOrder && (
        <div>
          <label className="label">{t("field.orderNo")}</label>
          {orderOptions ? (
            <select
              className="input"
              value={selectedOrderId}
              onChange={(e) => {
                const productionOrderId = Number(e.target.value);
                const order = orderOptions.find((row) => Number(row.id) === productionOrderId);
                onChange({
                  ...form,
                  production_order_id: productionOrderId,
                  order_no: order?.orderNo || "",
                  item_id: 0,
                });
              }}
              required={requireOrder}
            >
              <option value={0}>{t("ph.orderNo")}</option>
              {orderOptions.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
            </select>
          ) : (
            <input className="input" placeholder={t("field.orderNo")} value={form.order_no} onChange={(e) => onChange({ ...form, order_no: e.target.value })} required={requireOrder} />
          )}
          {orderOptions && orderOptions.length === 0 && noOrderOptionsMessage && (
            <div className="mt-1 text-xs text-[#8a8472]">{noOrderOptionsMessage}</div>
          )}
        </div>
      )}
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
        <input className="input" type="number" step="0.01" placeholder={t("field.netto")} value={form.quantity} onChange={(e) => onChange({ ...form, quantity: numericInputValue(e.target.value) })} required />
      </div>
      {showGramaj && (
        <div>
          <label className="label">{t("field.gramaj")}</label>
          <input className="input" type="number" min={0} step="0.000001" placeholder="0.145" value={form.gsm} onChange={(e) => onChange({ ...form, gsm: e.target.value })} />
        </div>
      )}
      <div>
        <label className="label">{t("field.pieceCount")}</label>
        <input className="input" type="number" min={0} placeholder={t("field.pieceCount")} value={form.piece_count} onChange={(e) => onChange({ ...form, piece_count: numericInputValue(e.target.value) })} />
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
        <input className="input" type="number" step="0.01" placeholder={t("field.cost") + " / " + t("field.unit")} value={form.cost_per_unit} onChange={(e) => onChange({ ...form, cost_per_unit: numericInputValue(e.target.value) })} />
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
  const searchParams = useSearchParams();
  const preselectedIssueProductionOrderId = Number(searchParams.get("issue_production_order_id") || 0);
  const { data: materialItems } = useSWR<any[]>("/api/inventory/items?group=materials", fetcher);
  const { data: accessoryItems } = useSWR<any[]>("/api/inventory/items?group=accessories", fetcher);
  const { data: warehouses } = useSWR<any[]>("/api/inventory/warehouses", fetcher);
  const { data: suppliers } = useSWR<any[]>("/api/suppliers", fetcher);
  const { data: productionOrders } = useSWR<any[]>("/api/production-orders?page_size=500", fetcher);
  const { data: models } = useSWR<any[]>("/api/models", fetcher);
  const { data: batches, mutate: refreshBatches } = useSWR<any[]>("/api/inventory/batches", fetcher);
  const { data: accessoryIssueRows, mutate: refreshAccessoryIssues } = useSWR<AccessoryIssueSummaryRow[]>("/api/inventory/accessory-issues?page_size=500", fetcher);
  const [receiveForm, setReceiveForm] = useState(DEFAULT_RECEIVE_FORM);
  const [accessoryReturnForm, setAccessoryReturnForm] = useState(DEFAULT_ACCESSORY_RETURN_FORM);
  const [issueProductionOrderId, setIssueProductionOrderId] = useState(0);
  const [issueQuantities, setIssueQuantities] = useState<Record<number, string>>({});
  const [receiveMsg, setReceiveMsg] = useState("");
  const [accessoryMsg, setAccessoryMsg] = useState("");
  const [issueMsg, setIssueMsg] = useState("");
  const [issueBusy, setIssueBusy] = useState(false);
  const [customColors, setCustomColors] = useState<string[]>([]);
  const [uploadingReceiveImage, setUploadingReceiveImage] = useState(false);
  const { data: issuePlan, mutate: refreshIssuePlan } = useSWR<AccessoryIssuePlan>(
    issueProductionOrderId ? `/api/inventory/accessory-issue-plan?production_order_id=${issueProductionOrderId}` : null,
    fetcher,
  );
  const modelById = useMemo(() => new Map((models || []).map((m) => [Number(m.id), m])), [models]);
  const receiveItems = useMemo<ReceiveItem[]>(() => {
    return [...(materialItems || []), ...(accessoryItems || [])].sort((a, b) => {
      const left = `${a.category || ""} ${a.name || ""}`;
      const right = `${b.category || ""} ${b.name || ""}`;
      return left.localeCompare(right);
    });
  }, [accessoryItems, materialItems]);
  const returnableAccessoryIssueRows = useMemo(() => {
    return (accessoryIssueRows || []).filter((row) => Number(row.returnable_quantity ?? row.issued_quantity ?? 0) > 0);
  }, [accessoryIssueRows]);
  const accessoryReturnOrderOptions = useMemo<OrderOption[]>(() => {
    const byOrder = new Map<number, OrderOption>();
    for (const row of returnableAccessoryIssueRows) {
      const id = Number(row.production_order_id);
      if (byOrder.has(id)) continue;
      const modelText = [row.model_code, row.model_name].filter(Boolean).join(" - ");
      byOrder.set(id, {
        id,
        orderNo: row.order_no || row.production_no,
        label: [orderReference(row, row.production_no), modelText].filter(Boolean).join(" - "),
      });
    }
    return [...byOrder.values()];
  }, [returnableAccessoryIssueRows]);
  const selectedAccessoryReturnRows = useMemo(() => {
    return returnableAccessoryIssueRows.filter(
      (row) => Number(row.production_order_id) === Number(accessoryReturnForm.production_order_id),
    );
  }, [accessoryReturnForm.production_order_id, returnableAccessoryIssueRows]);
  const returnableAccessoryItems = useMemo<ReceiveItem[]>(() => {
    return selectedAccessoryReturnRows.map((row) => ({
      id: row.item_id,
      name: `${row.item_name} (${fmtQty(row.returnable_quantity ?? row.issued_quantity)} ${row.unit})`,
      category: row.category,
      unit: row.unit,
    }));
  }, [selectedAccessoryReturnRows]);

  useEffect(() => {
    if (preselectedIssueProductionOrderId > 0) {
      setIssueProductionOrderId(preselectedIssueProductionOrderId);
    }
  }, [preselectedIssueProductionOrderId]);

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

  async function uploadReceiveItemImage(file?: File | null) {
    if (!file) return;
    if (!receiveForm.item_id) {
      setReceiveMsg(t("page.receiveStock.selectItemForImage"));
      return;
    }
    setUploadingReceiveImage(true);
    setReceiveMsg("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await api.postForm<{ file_url: string }>("/api/inventory/items/image/upload", form);
      setReceiveForm((current) => ({ ...current, image_url: response.file_url }));
      setReceiveMsg(t("page.receiveStock.itemImageUpdated"));
    } catch (e: any) {
      setReceiveMsg(e.message || t("page.masterData.imageUploadFailed"));
    } finally {
      setUploadingReceiveImage(false);
    }
  }

  async function submitAccessoryReturn(e: React.FormEvent) {
    e.preventDefault();
    setAccessoryMsg("");
    if (!accessoryReturnForm.production_order_id) {
      setAccessoryMsg(t("page.receiveStock.selectIssuedOrder"));
      return;
    }
    try {
      await api.post("/api/inventory/accessory-returns", toAccessoryReturnPayload(accessoryReturnForm));
      setAccessoryMsg(t("msg.recorded"));
      setAccessoryReturnForm(DEFAULT_ACCESSORY_RETURN_FORM);
      refreshBatches();
      refreshAccessoryIssues();
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

  function addCustomColor(color: string) {
    setCustomColors((current) => (
      current.some((option) => option.toLowerCase() === color.toLowerCase()) ? current : [...current, color]
    ));
  }

  return (
    <div>
      <PageHeader title={t("page.receiveStock.title")} subtitle={t("page.receiveStock.subtitle")} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <StockForm
          title={t("page.receiveStock.materialForm")}
          itemLabel={`${t("field.materialName")} / ${t("field.accessory")}`}
          submitLabel={t("btn.receive")}
          form={receiveForm}
          items={receiveItems}
          warehouses={warehouses}
          suppliers={suppliers}
          message={receiveMsg}
          showOrder={false}
          showGramaj
          showItemImage
          uploadingImage={uploadingReceiveImage}
          customColors={customColors}
          onChange={setReceiveForm}
          onAddColor={addCustomColor}
          onUploadItemImage={uploadReceiveItemImage}
          onSubmit={submitReceive}
        />
        <StockForm
          title={t("page.receiveStock.accessoryReturnTitle")}
          subtitle={t("page.receiveStock.accessoryReturnSubtitle")}
          itemLabel={t("field.accessory")}
          submitLabel={t("btn.collectBack")}
          form={accessoryReturnForm}
          items={returnableAccessoryItems}
          warehouses={warehouses}
          suppliers={suppliers}
          orderOptions={accessoryReturnOrderOptions}
          message={accessoryMsg}
          requireOrder
          showReturnCondition
          noOrderOptionsMessage={t("page.receiveStock.noReturnableAccessories")}
          customColors={customColors}
          onChange={setAccessoryReturnForm}
          onAddColor={addCustomColor}
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
                  <td colSpan={7} className="text-sm text-slate-400">{t("page.receiveStock.noAccessoryBom")}</td>
                </tr>
              )}
              {!issueProductionOrderId && (
                <tr>
                  <td colSpan={7} className="text-sm text-slate-400">{t("page.receiveStock.selectPoFirst")}</td>
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
              <th>{t("field.gramaj").toUpperCase()}</th>
              <th>{t("field.pieceCount").toUpperCase()}</th>
              <th>{t("field.processes").toUpperCase()}</th>
            </tr>
          </thead>
          <tbody>
              {batches?.slice(0, 30).map((b) => (
              <tr key={b.id}>
                <td>{b.batch_no}</td>
                <td>{b.item_name || b.item_id}</td>
                <td>{materialColorLabel(b.color, t)}</td>
                <td>{b.old_code || "-"}</td>
                <td>{b.color_code || "-"}</td>
                <td>{b.color_status || "-"}</td>
                <td>{b.order_no || "-"}</td>
                <td>{Number(b.quantity).toFixed(2)}</td>
                <td>{b.gsm != null ? Number(b.gsm).toFixed(3) : "-"}</td>
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
