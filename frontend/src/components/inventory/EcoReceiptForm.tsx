"use client";
import { Fragment, useId, useRef, useState } from "react";
import Link from "next/link";
import { Plus, Trash2 } from "lucide-react";
import useSWR from "swr";
import SearchableSelect from "@/components/SearchableSelect";
import MaterialRollWeightFields from "@/components/MaterialRollWeightFields";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { can, useMe } from "@/lib/auth";
import { InventoryQcStatus } from "@/lib/inventoryQcStatus";
import { ecoInventoryText, type EcoMaterialItem, type EcoMaterialKind } from "@/lib/ecoInventory";
import { ecoReceiptText, ecoQualityText, type EcoReceiptBulkBody, type EcoReceiptSource } from "@/lib/ecoReceipt";
import { newEcoReceiptRow, ecoReceiptRowBody, ecoReceiptTableText, type EcoReceiptRow } from "@/lib/ecoReceiptTable";

type Option = { id: number; name: string };
const qcOptions = [InventoryQcStatus.PENDING, InventoryQcStatus.PASSED, InventoryQcStatus.FAILED, InventoryQcStatus.HOLD];
export default function EcoReceiptForm({ kind, busy, onSubmit, onCancel }: {
  kind: EcoMaterialKind; busy: boolean; onSubmit: (body: EcoReceiptBulkBody) => void; onCancel: () => void;
}) {
  const { lang, t } = useT(); const { me } = useMe(); const text = ecoInventoryText(lang); const receipt = ecoReceiptText(lang); const labels = ecoReceiptTableText(lang);
  const { data: items, error: itemError } = useSWR<EcoMaterialItem[]>(`/api/eco-inventory/items?kind=${kind}`, fetcher);
  const { data: suppliers } = useSWR<Option[]>("/api/eco-inventory/suppliers", fetcher);
  const { data: warehouses, mutate: refreshWarehouses } = useSWR<Option[]>("/api/eco-inventory/warehouses", fetcher);
  const { data: orders } = useSWR<{id: number; order_no: string}[]>("/api/eco-inventory/orders", fetcher);
  const initialRowId = useId();
  const [rows, setRows] = useState<EcoReceiptRow[]>(() => [{...newEcoReceiptRow(kind), key: initialRowId}]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const tableRef = useRef<HTMLTableElement>(null);
  const [source, setSource] = useState<EcoReceiptSource>("opening_balance");
  const [warehouseId, setWarehouseId] = useState<number | null>(null); const [warehouseName, setWarehouseName] = useState<string | null>(null);
  const [supplierId, setSupplierId] = useState<number | null>(null); const [orderId, setOrderId] = useState<number | null>(null);
  const [date, setDate] = useState(new Date().toLocaleDateString("en-CA", {timeZone: "Asia/Tashkent"}));
  const [documentNo, setDocumentNo] = useState(""); const [error, setError] = useState(""); const [adding, setAdding] = useState(false);
  const fabric = kind === "fabric";
  function update(key: string, patch: Partial<EcoReceiptRow>) {setRows(current => current.map(row => row.key === key ? {...row, ...patch} : row));}
  function detail(row: EcoReceiptRow, key: string, value: string) {update(row.key, {details: {...row.details, [key]: value}});}
  function addRow() {
    if (rows.length >= 100 || busy || adding) return;
    const row = newEcoReceiptRow(kind); setRows(current => [...current, row]);
    requestAnimationFrame(() => tableRef.current?.querySelector<HTMLInputElement>(`[data-row-key="${row.key}"] input`)?.focus());
  }
  function field(row: EcoReceiptRow, key: string, label: string, type = "text", primary = false) {
    return <label className={primary ? "block" : "label"} key={key}><span className={primary ? "sr-only" : undefined}>{label}</span><input className="input" aria-label={`${label} · ${rows.indexOf(row) + 1}`} type={type}
      step={type === "number" ? key === "piece_count" ? "1" : "any" : undefined} min={type === "number" ? key === "piece_count" ? "1" : "0.000001" : undefined}
      maxLength={type === "number" ? undefined : key === "image_url" ? 512 : key === "notes" ? 2000 : key === "processes" ? 255 : key === "color_code" ? 32 : 64}
      value={row.details[key] || ""} onChange={event => detail(row, key, event.target.value)} /></label>;
  }
  async function addWarehouse() {
    if (!warehouseName?.trim() || adding) return;
    setAdding(true); setError("");
    try { const row = await api.post<Option>("/api/eco-inventory/warehouses", {name: warehouseName.trim(), kind}); await refreshWarehouses(); setWarehouseId(row.id); setWarehouseName(null); }
    catch (failure) { setError(failure instanceof Error ? failure.message : text.error); }
    finally { setAdding(false); }
  }
  async function uploadImage(row: EcoReceiptRow, file: File | undefined) {
    if (!file || adding) return;
    setAdding(true); setError("");
    try { const body = new FormData(); body.append("file", file); const result = await api.postForm<{file_url: string}>("/api/inventory/items/image/upload", body);
      setRows(current => current.map(value => value.key === row.key ? {...value, details: {...value.details, image_url: result.file_url}} : value)); }
    catch (failure) {setError(failure instanceof Error ? failure.message : text.error);}
    finally {setAdding(false);}
  }
  function submit(event: React.FormEvent) {
    event.preventDefault(); setError("");
    if (!warehouseId || rows.some(row => !row.item_id || !row.batch_no.trim() || (row.mode === "rolls"
      ? !row.weights.length || row.weights.some(value => !/^\d+(\.\d{1,4})?$/.test(value) || Number(value) <= 0)
      : !Number.isFinite(Number(row.quantity)) || Number(row.quantity) <= 0))) {setError(labels.rowError); return;}
    onSubmit({request_key: crypto.randomUUID(), lines: rows.map(row => ({...ecoReceiptRowBody(row, kind), source,
      warehouse_id: warehouseId, supplier_id: supplierId, production_order_id: orderId,
      received_date: new Date(`${date}T00:00:00+05:00`).toISOString(), document_no: documentNo.trim() || null}))});
  }
  const columns = fabric ? 13 : 8;
  return <form className="card p-4 space-y-4" onSubmit={submit}>
    <h2 className="text-base font-semibold">{text.receive} · {text[kind]}</h2>
    <fieldset disabled={busy || adding} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <label className="label">{receipt.source}<select className="input" value={source} onChange={event => setSource(event.target.value as EcoReceiptSource)}>{(["opening_balance", "purchase", "other"] as const).map(value => <option key={value} value={value}>{receipt[value]}</option>)}</select></label>
        <label className="label">{receipt.receivedDate}<input className="input" type="date" value={date} required onChange={event => setDate(event.target.value)} /></label>
        <label className="label">{t("field.supplier")}<select className="input" value={supplierId || ""} onChange={event => setSupplierId(Number(event.target.value) || null)}><option value="">{labels.noSupplier}</option>{suppliers?.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        <div><label className="label" htmlFor="eco-receipt-warehouse">{t("ph.warehouse")}</label><select id="eco-receipt-warehouse" className="input" required value={warehouseId || ""} onChange={event => setWarehouseId(Number(event.target.value) || null)}><option value="">{t("ph.warehouse")}</option>{warehouses?.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><button className="mt-1 text-sm underline" type="button" onClick={() => setWarehouseName("")}>{receipt.addWarehouse}</button>
          {warehouseName !== null && <div className="mt-2 flex gap-2"><input className="input" aria-label={receipt.warehouseName} placeholder={receipt.warehouseName} value={warehouseName} maxLength={128} onChange={event => setWarehouseName(event.target.value)} /><button className="btn" type="button" disabled={!warehouseName.trim()} onClick={() => void addWarehouse()}>{text.save}</button></div>}</div>
        <label className="label">{receipt.document}<input className="input" maxLength={100} value={documentNo} onChange={event => setDocumentNo(event.target.value)} /></label>
        <div><label className="label" htmlFor="eco-receipt-order">{text.productionOrder}</label><SearchableSelect<number> inputId="eco-receipt-order" value={orderId} options={(orders || []).map(row => ({value: row.id, label: row.order_no}))} onChange={setOrderId} placeholder={text.none} noResultsText={text.empty} disabled={busy || adding} /></div>
      </div>
      <p className="text-sm text-[var(--erp-muted)]">{labels.keyboard}</p>
      <div className="overflow-x-auto"><table ref={tableRef} className="table w-full" style={{minWidth: fabric ? 1620 : 1080}}>
        <thead><tr>{["#", labels.type, labels.name, text.quantity, text.unit, text.batch, ...(fabric ? [t("field.pieceCount"), text.color, t("field.colorCode"), t("field.gramaj"), t("field.picture")] : []), labels.details, text.actions].map((label, i) => <th key={i}>{label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <Fragment key={row.key}><tr data-row-key={row.key}>
          <td>{index + 1}</td>
          <td className="min-w-36"><select className="input" aria-label={`${labels.type} · ${index + 1}`} value={row.category} onChange={event => update(row.key, {category: event.target.value as EcoMaterialItem["category"], item_id: null})}>{(fabric ? ["fabric", "semi_finished"] as const : ["accessory", "packaging"] as const).map(value => <option key={value} value={value}>{labels[value]}</option>)}</select></td>
          <td className="min-w-64"><SearchableSelect<number> inputId={`eco-item-${row.key}`} value={row.item_id} options={(items || []).filter(item => item.category === row.category).map(item => ({value: item.id, label: `${item.name} · ${item.sku}`}))}
            onChange={id => {const item = items?.find(value => value.id === id); update(row.key, {item_id: id, unit: item?.unit || row.unit, quantity: item?.unit && item.unit !== row.unit ? "" : row.quantity, mode: fabric && item?.unit === "m" ? "length" : "total"});}}
            placeholder={text.select} noResultsText={text.empty} required disabled={busy || adding} /></td>
          <td className="min-w-32"><input className="input" aria-label={`${text.quantity} · ${index + 1}`} type="number" required min="0.0001" step="0.0001" value={row.mode === "rolls" ? ecoReceiptRowBody({...row, weights: row.weights.filter(value => /^\d+(\.\d{1,4})?$/.test(value))}, kind).quantity : row.quantity} readOnly={row.mode === "rolls"} onChange={event => update(row.key, {quantity: event.target.value})} /></td>
          <td className="min-w-28">{fabric ? <select className="input" aria-label={`${text.unit} · ${index + 1}`} value={row.unit} onChange={event => update(row.key, {unit: event.target.value, quantity: "", mode: event.target.value === "m" ? "length" : "total"})}>{Array.from(new Set(["kg", "m", row.unit])).map(value => <option key={value}>{value}</option>)}</select> : <input className="input" aria-label={`${text.unit} · ${index + 1}`} value={row.unit} readOnly />}</td>
          <td className="min-w-36"><input className="input" aria-label={`${text.batch} · ${index + 1}`} required maxLength={64} value={row.batch_no} onChange={event => update(row.key, {batch_no: event.target.value})} onKeyDown={event => {if (event.key === "Enter") {event.preventDefault(); addRow();}}} /></td>
          {fabric && <><td className="min-w-24">{row.mode === "rolls" ? row.weights.length : field(row, "piece_count", t("field.pieceCount"), "number", true)}</td><td className="min-w-32">{field(row, "color", text.color, "text", true)}</td><td className="min-w-28">{field(row, "color_code", t("field.colorCode"), "text", true)}</td><td className="min-w-28">{field(row, "gsm", t("field.gramaj"), "number", true)}</td><td className="min-w-44"><input className="input text-xs" type="file" aria-label={`${t("page.masterData.uploadImage")} · ${index + 1}`} accept="image/png,image/jpeg,image/webp,image/gif" onChange={event => {void uploadImage(row, event.target.files?.[0]); event.target.value = "";}} />{row.details.image_url && <span className="text-xs">{labels.imageAdded}</span>}</td></>}
          <td><button className="btn whitespace-nowrap" type="button" aria-expanded={!!expanded[row.key]} onClick={() => setExpanded(current => ({...current, [row.key]: !current[row.key]}))}>{labels.details}</button></td>
          <td><button className="icon-btn" type="button" title={`${labels.remove} · ${index + 1}`} aria-label={`${labels.remove} · ${index + 1}`} disabled={rows.length === 1} onClick={() => setRows(current => current.filter(value => value.key !== row.key))}><Trash2 className="h-4 w-4" /></button></td>
        </tr><tr hidden={!expanded[row.key]}><td colSpan={columns} className="bg-[var(--erp-bg)]"><div className="grid gap-4 p-2 sm:grid-cols-2 xl:grid-cols-4">
          {fabric && <><label className="label">{t("fabricRollEntry.quantityMethod")}<select className="input" value={row.mode} onChange={event => {const mode = event.target.value as EcoReceiptRow["mode"]; update(row.key, {mode, quantity: "", unit: mode === "length" ? "m" : "kg"});}}><option value="total">{t("fabricRollEntry.totalOnly")}</option><option value="rolls">{t("fabricRollEntry.individual")}</option><option value="length">{t("fabricRollEntry.totalLengthOnly")}</option></select></label>
            {row.mode === "rolls" && <MaterialRollWeightFields values={row.weights} lengths={row.lengths} onChange={(weights, lengths) => update(row.key, {weights, lengths})} />}</>}
          <label className="label">{receipt.cost} · {row.unit}<input className="input" type="number" min="0" step="0.0001" required value={row.cost_per_unit} onChange={event => update(row.key, {cost_per_unit: event.target.value})} /></label>
          <label className="label">{receipt.inspection}<select className="input" value={row.qc_status} onChange={event => update(row.key, {qc_status: event.target.value as InventoryQcStatus})}>{qcOptions.map(value => <option key={value} value={value}>{ecoQualityText(value, t, receipt)}</option>)}</select></label>
          {!fabric && <>{field(row, "color", text.color)}{field(row, "piece_count", t("field.pieceCount"), "number")}</>}
          {fabric && <>{field(row, "old_code", t("field.oldCode"))}{field(row, "color_status", t("field.colorStatus"))}{field(row, "width", receipt.width, "number")}{row.mode !== "length" && field(row, "length_m", receipt.length, "number")}</>}
          {field(row, "processes", t("field.processes"))}{field(row, "image_url", t("page.masterData.imageUrl"))}
          {!fabric && <label className="label">{t("page.masterData.uploadImage")}<input className="input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={event => {void uploadImage(row, event.target.files?.[0]); event.target.value = "";}} /></label>}
          {field(row, "notes", text.notes)}
        </div></td></tr></Fragment>)}</tbody>
      </table></div>
      <div className="flex flex-wrap justify-between gap-3"><button className="btn" type="button" disabled={rows.length >= 100} onClick={addRow}><Plus className="h-4 w-4" />{labels.addRow}</button>
        {can(me, "storage.items") && <Link className="text-sm underline" href={`/eco-inventory/catalog?group=${fabric ? "materials" : "accessories"}`}>{fabric ? receipt.addFabric : receipt.addAccessory}</Link>}</div>
      {rows.length >= 100 && <p className="text-sm">{labels.maxRows}</p>}
    </fieldset>
    {itemError && <p role="alert">{text.error}</p>}{error && <p role="alert" className="text-red-700">{error}</p>}
    <div className="flex gap-2"><button className="btn btn-primary" disabled={busy || adding}>{busy ? text.loading : text.save}</button><button className="btn" type="button" disabled={busy || adding} onClick={onCancel}>{text.cancel}</button></div>
  </form>;
}
