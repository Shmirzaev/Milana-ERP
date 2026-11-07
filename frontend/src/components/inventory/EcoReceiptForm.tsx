"use client";
import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import SearchableSelect from "@/components/SearchableSelect";
import MaterialRollWeightFields, { rollWeightsTotal, validRollWeights } from "@/components/MaterialRollWeightFields";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { InventoryQcStatus } from "@/lib/inventoryQcStatus";
import { ecoInventoryText, type EcoMaterialItem, type EcoMaterialKind } from "@/lib/ecoInventory";
import { ecoReceiptText, ecoQualityText, type EcoReceiptBody, type EcoReceiptSource } from "@/lib/ecoReceipt";

type Option = { id: number; name: string };
const qcOptions = [InventoryQcStatus.PENDING, InventoryQcStatus.PASSED, InventoryQcStatus.FAILED, InventoryQcStatus.HOLD];
export default function EcoReceiptForm({ kind, busy, onSubmit, onCancel }: {
  kind: EcoMaterialKind; busy: boolean; onSubmit: (body: EcoReceiptBody) => void; onCancel: () => void;
}) {
  const { lang, t } = useT(); const { me } = useMe(); const text = ecoInventoryText(lang); const receipt = ecoReceiptText(lang);
  const { data: items, error: itemError } = useSWR<EcoMaterialItem[]>(`/api/eco-inventory/items?kind=${kind}`, fetcher);
  const { data: suppliers } = useSWR<Option[]>("/api/eco-inventory/suppliers", fetcher);
  const { data: warehouses, mutate: refreshWarehouses } = useSWR<Option[]>("/api/eco-inventory/warehouses", fetcher);
  const { data: orders } = useSWR<{id: number; order_no: string}[]>("/api/eco-inventory/orders", fetcher);
  const [itemId, setItemId] = useState<number | null>(null); const [batch, setBatch] = useState("");
  const [unit, setUnit] = useState(kind === "fabric" ? "kg" : "pcs"); const [quantity, setQuantity] = useState("");
  const [mode, setMode] = useState<"rolls" | "total" | "length">("total");
  const [weights, setWeights] = useState([""]); const [lengths, setLengths] = useState([""]);
  const [source, setSource] = useState<EcoReceiptSource>("opening_balance");
  const [warehouseId, setWarehouseId] = useState<number | null>(null); const [warehouseName, setWarehouseName] = useState<string | null>(null);
  const [supplierId, setSupplierId] = useState<number | null>(null); const [orderId, setOrderId] = useState<number | null>(null);
  const [date, setDate] = useState(new Date().toLocaleDateString("en-CA", {timeZone: "Asia/Tashkent"}));
  const [cost, setCost] = useState("0"); const [qc, setQc] = useState<InventoryQcStatus>(InventoryQcStatus.PASSED);
  const [values, setValues] = useState<Record<string, string>>({}); const [error, setError] = useState(""); const [adding, setAdding] = useState(false);
  const fabric = kind === "fabric"; const individual = fabric && mode === "rolls";
  const total = individual ? rollWeightsTotal(weights).toFixed(4) : quantity;
  const group = fabric ? "materials" : "accessories";
  function field(key: string, label: string, type = "text") { return <label className="label" key={key}>{label}<input className="input" type={type} step={type === "number" ? "any" : undefined} min={type === "number" ? "0.000001" : undefined} maxLength={type === "number" ? undefined : key === "image_url" ? 512 : key === "notes" ? 2000 : 100} value={values[key] || ""} onChange={event => setValues({...values, [key]: event.target.value})} /></label>; }
  async function addWarehouse() {
    if (!warehouseName?.trim() || adding) return;
    setAdding(true); setError("");
    try { const row = await api.post<Option>("/api/eco-inventory/warehouses", {name: warehouseName.trim(), kind}); await refreshWarehouses(); setWarehouseId(row.id); setWarehouseName(null); }
    catch (failure) { setError(failure instanceof Error ? failure.message : text.error); }
    finally { setAdding(false); }
  }
  async function uploadImage(file: File | undefined) {
    if (!file || adding) return;
    setAdding(true); setError("");
    try { const body = new FormData(); body.append("file", file); const result = await api.postForm<{file_url: string}>("/api/inventory/items/image/upload", body); setValues(current => ({...current, image_url: result.file_url})); }
    catch (failure) {setError(failure instanceof Error ? failure.message : text.error);}
    finally {setAdding(false);}
  }
  function submit(event: React.FormEvent) {
    event.preventDefault(); setError("");
    if (!itemId || !warehouseId || Number(total) <= 0 || !Number.isFinite(Number(total)) || (individual && !validRollWeights(weights))) { setError(receipt.invalid); return; }
    onSubmit({ request_key: crypto.randomUUID(), kind, item_id: itemId, batch_no: batch.trim(), color: values.color?.trim() || null,
      quantity: total, unit, source, warehouse_id: warehouseId, supplier_id: supplierId, production_order_id: orderId,
      received_date: new Date(`${date}T00:00:00+05:00`).toISOString(), document_no: values.document_no || null,
      cost_per_unit: cost, qc_status: qc, notes: values.notes || null, old_code: values.old_code || null,
      color_code: values.color_code || null, color_status: values.color_status || null, width: values.width || null,
      gsm: values.gsm || null, length_m: mode === "length" ? total : values.length_m || null,
      piece_count: individual ? weights.length : values.piece_count ? Number(values.piece_count) : null,
      roll_weights_kg: individual ? weights : [], roll_lengths_m: individual ? lengths.map(value => value || null) : [],
      processes: values.processes || null, image_url: values.image_url || null });
  }
  return <form className="card p-6 space-y-4" onSubmit={submit}>
    <h2 className="text-base font-semibold">{text.receive} · {text[kind]}</h2><p className="text-sm text-[var(--erp-muted)]">{receipt.receiptHelp}</p>
    <fieldset disabled={busy || adding} className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <label className="label">{receipt.source}<select className="input" value={source} onChange={event => setSource(event.target.value as EcoReceiptSource)}>{(["opening_balance", "purchase", "other"] as const).map(value => <option key={value} value={value}>{receipt[value]}</option>)}</select></label>
      <label className="label">{receipt.receivedDate}<input className="input" type="date" value={date} required onChange={event => setDate(event.target.value)} /></label>
      <div><label className="label" htmlFor="eco-receipt-item">{text.item}</label><SearchableSelect<number> inputId="eco-receipt-item" value={itemId} options={(items || []).map(item => ({value: item.id, label: `${item.name} · ${item.sku} · ${item.unit}`}))} onChange={id => {setItemId(id); const nextUnit = items?.find(item => item.id === id)?.unit || unit; setUnit(nextUnit); if (fabric) setMode(nextUnit === "m" ? "length" : "total");}} placeholder={text.select} noResultsText={text.empty} required />
        {can(me, "storage.items") && <Link className="inline-block mt-2 text-sm underline" href={`/eco-inventory/catalog?group=${group}`}>{fabric ? receipt.addFabric : receipt.addAccessory}</Link>}
        {itemError && <p role="alert">{text.error}</p>}</div>
      <label className="label">{text.batch}<input className="input" required maxLength={64} value={batch} onChange={event => setBatch(event.target.value)} /></label>
      {field("color", text.color)}{field("document_no", receipt.document)}
      {fabric && <><label className="label md:col-span-2">{t("fabricRollEntry.quantityMethod")}<select className="input" value={mode} onChange={event => {const next = event.target.value as typeof mode; setMode(next); setUnit(next === "length" ? "m" : "kg"); setQuantity("");}}><option value="total">{t("fabricRollEntry.totalOnly")}</option><option value="rolls">{t("fabricRollEntry.individual")}</option><option value="length">{t("fabricRollEntry.totalLengthOnly")}</option></select></label>
        {individual && <MaterialRollWeightFields values={weights} lengths={lengths} onChange={(next, meters) => {setWeights(next); setLengths(meters);}} />}</>}
      <label className="label">{text.quantity} · {unit}<input className="input" type="number" min="0.0001" step="0.0001" required value={total} readOnly={individual} onChange={event => setQuantity(event.target.value)} /></label>
      <label className="label">{text.unit}<input className="input" required maxLength={32} value={unit} readOnly /></label>
      {!individual && field("piece_count", t("field.pieceCount"), "number")}
      <label className="label">{t("ph.supplier")}<select className="input" value={supplierId || ""} onChange={event => setSupplierId(Number(event.target.value) || null)}><option value="">{text.none}</option>{suppliers?.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      <div><label className="label" htmlFor="eco-receipt-warehouse">{t("ph.warehouse")}</label><select id="eco-receipt-warehouse" className="input" required value={warehouseId || ""} onChange={event => setWarehouseId(Number(event.target.value) || null)}><option value="">{t("ph.warehouse")}</option>{warehouses?.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><button className="btn mt-2" type="button" onClick={() => setWarehouseName("")}>{receipt.addWarehouse}</button>
        {warehouseName !== null && <div className="mt-2 flex gap-2"><input className="input" aria-label={receipt.warehouseName} placeholder={receipt.warehouseName} value={warehouseName} maxLength={128} onChange={event => setWarehouseName(event.target.value)} /><button className="btn" type="button" disabled={!warehouseName.trim()} onClick={() => void addWarehouse()}>{text.save}</button></div>}</div>
      <label className="label">{receipt.cost} · {unit}<input className="input" type="number" min="0" step="0.0001" required value={cost} onChange={event => setCost(event.target.value)} /></label>
      <label className="label">{receipt.inspection}<select className="input" value={qc} onChange={event => setQc(event.target.value as InventoryQcStatus)}>{qcOptions.map(value => <option key={value} value={value}>{ecoQualityText(value, t, receipt)}</option>)}</select></label>
      {fabric && <>{field("old_code", t("field.oldCode"))}{field("color_code", t("field.colorCode"))}{field("color_status", t("field.colorStatus"))}{field("width", receipt.width, "number")}{field("gsm", t("field.gramaj"), "number")}{mode !== "length" && field("length_m", receipt.length, "number")}</>}
      {field("processes", t("field.processes"))}{field("image_url", t("page.masterData.imageUrl"))}
      <label className="label">{t("page.masterData.uploadImage")}<input className="input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={event => {void uploadImage(event.target.files?.[0]); event.target.value = "";}} /></label>
      <div><label className="label" htmlFor="eco-receipt-order">{text.productionOrder}</label><SearchableSelect<number> inputId="eco-receipt-order" value={orderId} options={(orders || []).map(row => ({value: row.id, label: row.order_no}))} onChange={setOrderId} placeholder={text.none} noResultsText={text.empty} /></div>
      {field("notes", text.notes)}
    </fieldset>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    <div className="flex gap-2"><button className="btn btn-primary" disabled={busy || adding}>{busy ? text.loading : text.save}</button><button className="btn" type="button" disabled={busy} onClick={onCancel}>{text.cancel}</button></div>
  </form>;
}
