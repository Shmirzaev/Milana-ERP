"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Check, ChevronDown, Folder, ImagePlus, PackageCheck, Plus, ShoppingCart, X } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { prepareModelImageUpload } from "@/lib/imageUpload";

type Item = { id: number; sku: string; name: string; unit: string; image_url?: string | null };
type Supplier = { id: number; name: string };
type PurchaseRequestLine = {
  id: number; item_id: number; item_sku?: string | null; item_name?: string | null;
  material_name?: string | null; photo_url?: string | null; requested_quantity: number;
  shortage_quantity: number; unit: string; preferred_supplier_id?: number | null;
  preferred_supplier_name?: string | null;
};
type PurchaseRequest = {
  id: number; request_no: string; status: string; sales_order_no?: string | null;
  lines: PurchaseRequestLine[];
};
type PurchaseOrder = { id: number; status: string; lines: { id: number; remaining_quantity: number }[] };
type ApprovalLineDraft = { material_name: string; photo_url: string; preferred_supplier_id: number };
type OrderDraft = { expected_date: string; quantities: Record<number, string> };

const RECEIVABLE_ORDER_STATUSES = new Set(["sent", "approved", "partially_received"]);
const ACTIVE_REQUEST_STATUSES = new Set(["draft", "pending_approval", "approved"]);

function fmtQty(value: number | string | null | undefined) {
  const n = Number(value || 0);
  return Number.isFinite(n) ? n.toFixed(2) : "0.00";
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useT();
  const tone = status === "approved"
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : status === "rejected"
      ? "border-red-200 bg-red-50 text-red-700"
      : "border-[#ded9ca] bg-[#f7f4ed] text-[#56503f]";
  return <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${tone}`}>{statusLabel(status, t)}</span>;
}

export default function PurchasingPage() {
  const { t } = useT();
  const { me } = useMe();
  const canView = can(me, "purchasing.view");
  const canRequest = can(me, "purchasing.request");
  const canApprove = can(me, "purchasing.approve");
  const canOrder = can(me, "purchasing.order");
  const [message, setMessage] = useState("");
  const [showRequestForm, setShowRequestForm] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [uploadingKey, setUploadingKey] = useState<string | null>(null);
  const [manual, setManual] = useState({ item_id: 0, material_name: "", supplier_id: 0, photo_url: "", notes: "" });
  const [approvalDrafts, setApprovalDrafts] = useState<Record<number, ApprovalLineDraft>>({});
  const [orderDrafts, setOrderDrafts] = useState<Record<number, OrderDraft>>({});

  const { data: requests, mutate: refreshRequests } = useSWR<PurchaseRequest[]>(canView ? "/api/purchasing/requests" : null, fetcher);
  const { data: orders, mutate: refreshOrders } = useSWR<PurchaseOrder[]>(canView ? "/api/purchasing/orders" : null, fetcher);
  const { data: materialItems } = useSWR<Item[]>(canRequest || canApprove ? "/api/inventory/items?group=materials&page_size=500" : null, fetcher);
  const { data: accessoryItems } = useSWR<Item[]>(canRequest || canApprove ? "/api/inventory/items?group=accessories&page_size=500" : null, fetcher);
  const { data: suppliers } = useSWR<Supplier[]>(canRequest || canApprove ? "/api/suppliers" : null, fetcher);
  const items = useMemo(() => [...(materialItems || []), ...(accessoryItems || [])].sort((a, b) => a.name.localeCompare(b.name)), [materialItems, accessoryItems]);

  useEffect(() => {
    if (!requests) return;
    setApprovalDrafts((current) => {
      const next = { ...current };
      for (const request of requests) for (const line of request.lines) {
        if (!next[line.id]) next[line.id] = {
          material_name: line.material_name || line.item_name || "",
          photo_url: line.photo_url || "",
          preferred_supplier_id: Number(line.preferred_supplier_id || 0),
        };
      }
      return next;
    });
    setOrderDrafts((current) => {
      const next = { ...current };
      for (const request of requests.filter((row) => row.status === "approved")) {
        if (!next[request.id]) next[request.id] = {
          expected_date: "",
          quantities: Object.fromEntries(request.lines.map((line) => [line.id, Number(line.requested_quantity || 0) > 0 ? String(Number(line.requested_quantity)) : ""])),
        };
      }
      return next;
    });
  }, [requests]);

  async function uploadPhoto(file: File, key: string, onDone: (url: string) => void) {
    setUploadingKey(key);
    setMessage("");
    try {
      const prepared = await prepareModelImageUpload(file);
      const body = new FormData();
      body.append("file", prepared);
      const result = await api.postForm<{ file_url: string }>("/api/purchasing/request-photo/upload", body);
      onDone(result.file_url);
    } catch (error: any) {
      setMessage(error?.message || t("page.purchasing.actionFailed"));
    } finally {
      setUploadingKey(null);
    }
  }

  async function submitManualRequest(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const item = items.find((row) => row.id === manual.item_id);
    if (!item || !manual.material_name.trim() || !manual.supplier_id || !manual.photo_url) {
      setMessage(t("page.purchasing.approvalDetailsRequired"));
      return;
    }
    setBusyId(-1);
    try {
      const created = await api.post<PurchaseRequest>("/api/purchasing/requests", {
        status: "pending_approval", notes: manual.notes.trim() || null,
        lines: [{
          item_id: item.id, unit: item.unit, required_quantity: 0, requested_quantity: 0,
          available_quantity: 0, shortage_quantity: 0, preferred_supplier_id: manual.supplier_id,
          material_name: manual.material_name.trim(), photo_url: manual.photo_url,
        }],
      });
      setManual({ item_id: 0, material_name: "", supplier_id: 0, photo_url: "", notes: "" });
      setShowRequestForm(false);
      setMessage(t("page.purchasing.requestSent", { requestNo: created.request_no }));
      refreshRequests();
    } catch (error: any) {
      setMessage(error?.message || t("page.purchasing.actionFailed"));
    } finally {
      setBusyId(null);
    }
  }

  async function approve(request: PurchaseRequest) {
    const lines = request.lines.map((line) => ({
      purchase_request_line_id: line.id,
      material_name: approvalDrafts[line.id]?.material_name.trim() || "",
      preferred_supplier_id: Number(approvalDrafts[line.id]?.preferred_supplier_id || 0),
      photo_url: approvalDrafts[line.id]?.photo_url || "",
    }));
    if (lines.some((line) => !line.material_name || !line.preferred_supplier_id || !line.photo_url)) {
      setMessage(t("page.purchasing.approvalDetailsRequired")); return;
    }
    setBusyId(request.id); setMessage("");
    try {
      await api.post(`/api/purchasing/requests/${request.id}/approve`, { lines });
      setMessage(t("page.purchasing.approved")); refreshRequests();
    } catch (error: any) { setMessage(error?.message || t("page.purchasing.actionFailed")); }
    finally { setBusyId(null); }
  }

  async function reject(request: PurchaseRequest) {
    setBusyId(request.id); setMessage("");
    try {
      await api.post(`/api/purchasing/requests/${request.id}/reject`);
      await refreshRequests((current) => (current || []).filter((row) => row.id !== request.id), { revalidate: false });
    }
    catch (error: any) { setMessage(error?.message || t("page.purchasing.actionFailed")); }
    finally { setBusyId(null); }
  }

  async function order(request: PurchaseRequest) {
    const draft = orderDrafts[request.id];
    const lines = request.lines.map((line) => ({ purchase_request_line_id: line.id, ordered_quantity: Number(draft?.quantities[line.id] || 0) }));
    if (!draft?.expected_date || lines.some((line) => !Number.isFinite(line.ordered_quantity) || line.ordered_quantity <= 0)) {
      setMessage(t("page.purchasing.orderDetailsRequired")); return;
    }
    setBusyId(request.id); setMessage("");
    try {
      await api.post(`/api/purchasing/requests/${request.id}/convert-to-order`, { expected_date: `${draft.expected_date}T00:00:00`, lines });
      setMessage(t("page.purchasing.orderCreated")); refreshRequests(); refreshOrders();
    } catch (error: any) { setMessage(error?.message || t("page.purchasing.actionFailed")); }
    finally { setBusyId(null); }
  }

  const requestRows = (requests || []).filter((row) => ACTIVE_REQUEST_STATUSES.has(row.status));
  const supplierFolders = Array.from(requestRows.reduce((folders, request) => {
    const firstLine = request.lines[0];
    const firstLineDraft = firstLine ? approvalDrafts[firstLine.id] : undefined;
    const supplierId = Number(
      firstLineDraft?.preferred_supplier_id
      || firstLine?.preferred_supplier_id
      || 0,
    );
    const supplierName = suppliers?.find((supplier) => supplier.id === supplierId)?.name
      || firstLine?.preferred_supplier_name
      || t("ph.supplier");
    const key = supplierId ? `supplier-${supplierId}` : `supplier-${supplierName}`;
    const folder = folders.get(key) || { key, supplierName, requests: [] as PurchaseRequest[] };
    folder.requests.push(request);
    folders.set(key, folder);
    return folders;
  }, new Map<string, { key: string; supplierName: string; requests: PurchaseRequest[] }>()).values())
    .sort((a, b) => a.supplierName.localeCompare(b.supplierName));
  const openOrderCount = (orders || []).filter((row) => RECEIVABLE_ORDER_STATUSES.has(row.status) && row.lines.some((line) => Number(line.remaining_quantity || 0) > 0)).length;
  const today = new Date().toISOString().slice(0, 10);

  const renderRequestRows = (folderRequests: PurchaseRequest[]) => folderRequests.map((request) => (
    <Fragment key={request.id}>
      {request.lines.map((line, index) => {
        const draft = approvalDrafts[line.id] || { material_name: "", photo_url: "", preferred_supplier_id: 0 };
        const editable = canApprove && ["draft", "pending_approval"].includes(request.status);
        return <tr key={line.id}>
          <td><div className="mono font-semibold text-[#14110b]">{index === 0 ? request.request_no : ""}</div><div className="text-xs text-[#8a8472]">{index === 0 ? request.sales_order_no || "-" : ""}</div></td>
          <td><label className={`block h-[168px] w-[168px] overflow-hidden rounded-md border border-[#ded9ca] bg-[#f7f4ed] ${editable ? "cursor-pointer" : ""}`}>{draft.photo_url ? <img src={draft.photo_url} alt="" className="h-full w-full object-cover" /> : <span className="flex h-full items-center justify-center"><ImagePlus className="h-4 w-4 text-[#8a8472]" /></span>}{editable && <input type="file" accept="image/*" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) uploadPhoto(file, `line-${line.id}`, (photo_url) => setApprovalDrafts((rows) => ({ ...rows, [line.id]: { ...draft, photo_url } }))); }} />}</label></td>
          <td>{editable ? <input className="input min-w-[220px]" value={draft.material_name} onChange={(event) => setApprovalDrafts((rows) => ({ ...rows, [line.id]: { ...draft, material_name: event.target.value } }))} /> : <div><div className="font-medium text-[#14110b]">{draft.material_name || line.item_name || "-"}</div><div className="mono text-xs text-[#8a8472]">{line.item_sku || ""}</div></div>}</td>
          <td>{editable ? <select className="input min-w-[190px]" value={draft.preferred_supplier_id} onChange={(event) => setApprovalDrafts((rows) => ({ ...rows, [line.id]: { ...draft, preferred_supplier_id: Number(event.target.value) } }))}><option value={0}>{t("ph.supplier")}</option>{suppliers?.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select> : draft.preferred_supplier_id ? suppliers?.find((row) => row.id === draft.preferred_supplier_id)?.name || line.preferred_supplier_name || "-" : "-"}</td>
          <td className="mono">{fmtQty(line.requested_quantity || line.shortage_quantity)} {line.unit}</td>
          <td>{index === 0 && <StatusBadge status={request.status} />}</td>
          <td>{index === 0 && editable && <div className="flex gap-2"><button type="button" className="btn" disabled={busyId === request.id || Boolean(uploadingKey)} onClick={() => approve(request)}><Check className="h-4 w-4" />{t("btn.approve")}</button><button type="button" className="btn" disabled={busyId === request.id} onClick={() => reject(request)}><X className="h-4 w-4" />{t("btn.reject")}</button></div>}</td>
        </tr>;
      })}
      {request.status === "approved" && canOrder && <tr className="bg-[#fbfaf6]"><td colSpan={7}><div className="flex flex-wrap items-end gap-3 py-1">
        {request.lines.map((line) => <div key={line.id}><label className="label">{(line.material_name || line.item_name || line.item_sku)} ({line.unit || "kg"})</label><input className="input w-40" type="number" min="0.0001" step="0.0001" value={orderDrafts[request.id]?.quantities[line.id] || ""} onChange={(event) => setOrderDrafts((rows) => ({ ...rows, [request.id]: { ...(rows[request.id] || { expected_date: "", quantities: {} }), quantities: { ...(rows[request.id]?.quantities || {}), [line.id]: event.target.value } } }))} /></div>)}
        <div><label className="label">{t("page.purchasing.expectedDate")}</label><input className="input" type="date" min={today} value={orderDrafts[request.id]?.expected_date || ""} onChange={(event) => setOrderDrafts((rows) => ({ ...rows, [request.id]: { ...(rows[request.id] || { quantities: {} }), expected_date: event.target.value } }))} /></div>
        <button type="button" className="btn btn-primary" disabled={busyId === request.id} onClick={() => order(request)}><ShoppingCart className="h-4 w-4" />{t("page.purchasing.orderButton")}</button>
      </div></td></tr>}
    </Fragment>
  ));

  if (!canView) return <PageHeader title={t("page.purchasing.title")} subtitle={t("page.purchasing.noAccess")} />;

  return (
    <div>
      <PageHeader title={t("page.purchasing.title")} subtitle={t("page.purchasing.subtitle")} actions={(
        <div className="flex flex-wrap items-center justify-end gap-2">
          {canRequest && !showRequestForm && <button type="button" className="btn btn-primary" onClick={() => { setMessage(""); setShowRequestForm(true); }}><Plus className="h-4 w-4" />{t("page.purchasing.createSample")}</button>}
          <Link className="btn" href="/purchasing/receiving"><PackageCheck className="h-4 w-4" />{t("page.purchasing.activeOrders")} ({openOrderCount})</Link>
        </div>
      )} />
      {message && <div className="mb-4 rounded-md border border-[#ded9ca] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">{message}</div>}

      {canRequest && showRequestForm && (
        <form onSubmit={submitManualRequest} className="card mb-5 overflow-hidden">
          <div className="flex items-center justify-between border-b border-[#ecebe3] px-5 py-4">
            <h2 className="app-card-title">{t("page.purchasing.manualTitle")}</h2>
            <button type="button" className="icon-btn" aria-label={t("btn.cancel")} onClick={() => setShowRequestForm(false)}><X className="h-4 w-4" /></button>
          </div>
          <div className="grid grid-cols-1 gap-4 p-5 lg:grid-cols-[112px_minmax(0,1fr)]">
            <div>
              <label className="label">{t("page.purchasing.photo")}</label>
              <label className="flex h-24 w-24 cursor-pointer items-center justify-center overflow-hidden rounded-md border border-dashed border-[#cfc8b6] bg-[#fbfaf6] text-[#6f684f]">
                {manual.photo_url ? <img src={manual.photo_url} alt="" className="h-full w-full object-cover" /> : <ImagePlus className="h-5 w-5" />}
                <input type="file" accept="image/*" className="hidden" disabled={uploadingKey === "manual"} onChange={(event) => {
                  const file = event.target.files?.[0]; if (file) uploadPhoto(file, "manual", (photo_url) => setManual((row) => ({ ...row, photo_url })));
                }} />
              </label>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div><label className="label">{t("field.item")}</label><select className="input" value={manual.item_id} onChange={(event) => {
                const item = items.find((row) => row.id === Number(event.target.value));
                setManual((row) => ({ ...row, item_id: Number(event.target.value), material_name: item?.name || row.material_name, photo_url: item?.image_url || row.photo_url }));
              }} required><option value={0}>{t("page.purchasing.selectItem")}</option>{items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
              <div><label className="label">{t("field.supplier")}</label><select className="input" value={manual.supplier_id} onChange={(event) => setManual({ ...manual, supplier_id: Number(event.target.value) })} required><option value={0}>{t("ph.supplier")}</option>{suppliers?.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></div>
              <div><label className="label">{t("page.purchasing.materialName")}</label><input className="input" value={manual.material_name} onChange={(event) => setManual({ ...manual, material_name: event.target.value })} required /></div>
              <div><label className="label">{t("field.notes")}</label><input className="input" value={manual.notes} onChange={(event) => setManual({ ...manual, notes: event.target.value })} /></div>
            </div>
            <div className="flex justify-end gap-2 lg:col-start-2">
              <button type="button" className="btn" onClick={() => setShowRequestForm(false)}>{t("btn.cancel")}</button>
              <button className="btn btn-primary justify-center" disabled={busyId === -1 || uploadingKey === "manual"}><Plus className="h-4 w-4" />{t("page.purchasing.createRequest")}</button>
            </div>
          </div>
        </form>
      )}

      <section className="card mb-5 overflow-hidden">
        <div className="border-b border-[#ecebe3] px-5 py-4"><h2 className="app-card-title">{t("page.purchasing.requestsTitle")}</h2></div>
        <div className="space-y-3 p-5">
          {supplierFolders.map((folder) => (
            <details key={folder.key} open className="group overflow-hidden rounded-md border border-[#ded9ca] bg-white">
              <summary className="flex cursor-pointer list-none items-center gap-3 bg-[#fbfaf6] px-4 py-3.5 text-[#14110b] [&::-webkit-details-marker]:hidden">
                <Folder className="h-5 w-5 shrink-0 text-[#8a6f1f]" />
                <span className="min-w-0 flex-1 truncate font-semibold">{folder.supplierName}</span>
                <span className="mono rounded-md border border-[#ded9ca] bg-white px-2 py-0.5 text-xs text-[#6f684f]">{folder.requests.length}</span>
                <ChevronDown className="h-4 w-4 shrink-0 text-[#8a8472] transition-transform group-open:rotate-180" />
              </summary>
              <div className="overflow-x-auto border-t border-[#ecebe3]">
                <table className="table min-w-[1050px]">
                  <thead><tr><th>{t("field.purchaseRequest")}</th><th>{t("page.purchasing.photo")}</th><th>{t("page.purchasing.materialName")}</th><th>{t("field.supplier")}</th><th>{t("page.purchasing.suggestedQty")}</th><th>{t("common.status")}</th><th></th></tr></thead>
                  <tbody>{renderRequestRows(folder.requests)}</tbody>
                </table>
              </div>
            </details>
          ))}
          {requestRows.length === 0 && <div className="py-6 text-sm text-slate-400">{t("page.purchasing.noRequests")}</div>}
        </div>
      </section>
    </div>
  );
}
