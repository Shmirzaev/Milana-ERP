"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, useMemo, useState, type FormEvent } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import ConfirmDialog from "@/components/ConfirmDialog";
import Modal from "@/components/Modal";
import PageHeader from "@/components/PageHeader";
import PaginationControls from "@/components/PaginationControls";
import { productionTypeLabel, statusLabel } from "@/components/StagePipeline";
import { useT } from "@/lib/i18n";
import { orderReference } from "@/lib/orderRef";

type EditForm = {
  color: string;
  package_type: string;
  capacity: string;
  weight_kg: string;
  warehouse_id: string;
  storage_cell: string;
  storage_shelf: string;
  notes: string;
  reason: string;
  items: { model_id: number; color: string; size: string; quantity: string }[];
  batch_allocations: { production_batch_id: number; quantity: string }[];
};

export default function PackagesPage() {
  const { t } = useT();
  const searchParams = useSearchParams();
  const requestedDepartment = searchParams.get("packaging_department");
  const packagingDepartment = requestedDepartment === "ECP" || requestedDepartment === "BPK" ? requestedDepartment : "PKG";
  const isEcoCotton = packagingDepartment === "ECP";
  const factoryLabel = isEcoCotton ? "Eco Cotton" : packagingDepartment === "BPK" ? "Besttex" : "Milana";
  const { me } = useMe();
  const canApprovePackageChange = can(me, "management.approve");
  const canTraceability = can(me, "traceability.view");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const { data: pageData, mutate } = useSWR<any>(`/api/packages?include_total=true&page=${page}&page_size=${pageSize}&packaging_department_code=${packagingDepartment}`, fetcher);
  const { data: pendingRequests, mutate: mutatePendingRequests } = useSWR<any[]>(`/api/packages/change-requests?status=pending&packaging_department_code=${packagingDepartment}`, fetcher);
  const data = useMemo<any[]>(() => pageData?.rows || [], [pageData?.rows]);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState<any | null>(null);
  const [editForm, setEditForm] = useState<EditForm | null>(null);
  const [deleting, setDeleting] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [editLoading, setEditLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const pendingByPackage = useMemo(() => {
    const map = new Map<number, any>();
    for (const req of pendingRequests || []) {
      map.set(Number(req.package_id), req);
    }
    return map;
  }, [pendingRequests]);

  const editTotal = useMemo(() => (
    (editForm?.items || []).reduce((sum, row) => sum + Number(row.quantity || 0), 0)
  ), [editForm]);

  const groups = useMemo(() => {
    const map = new Map<
      string,
      {
        key: string;
        sales_order_id: number | null;
        production_order_id: number | null;
        order_no: string | null;
        sales_order_no: string | null;
        production_no: string | null;
        customer_name: string | null;
        order_type: string | null;
        total_quantity: number;
        packages: any[];
        latest_id: number;
      }
    >();

    for (const p of data || []) {
      const salesOrderId = p.sales_order_id == null ? null : Number(p.sales_order_id);
      const productionOrderId = p.production_order_id == null ? null : Number(p.production_order_id);
      const key = salesOrderId != null ? `so-${salesOrderId}` : `po-${productionOrderId ?? "none"}`;
      const existing = map.get(key) ?? {
        key,
        sales_order_id: salesOrderId,
        production_order_id: productionOrderId,
        order_no: p.order_no || p.sales_order_no || p.production_no || null,
        sales_order_no: p.sales_order_no || p.order_no || null,
        production_no: p.production_no || null,
        customer_name: p.customer_name || null,
        order_type: p.order_type || null,
        total_quantity: 0,
        packages: [],
        latest_id: 0,
      };
      existing.order_no = existing.order_no || p.order_no || p.sales_order_no || p.production_no || null;
      existing.sales_order_no = existing.sales_order_no || p.sales_order_no || p.order_no || null;
      existing.production_no = existing.production_no || p.production_no || null;
      existing.customer_name = existing.customer_name || p.customer_name || null;
      existing.order_type = existing.order_type || p.order_type || null;
      existing.total_quantity += Number(p.total_quantity || 0);
      existing.packages.push(p);
      existing.latest_id = Math.max(existing.latest_id, Number(p.id || 0));
      map.set(key, existing);
    }

    return Array.from(map.values())
      .map((g) => ({
        ...g,
        packages: [...g.packages].sort((a, b) => String(b.package_no || "").localeCompare(String(a.package_no || ""))),
      }))
      .sort((a, b) => b.latest_id - a.latest_id);
  }, [data]);

  function orderTitle(row: any) {
    return orderReference(row);
  }

  function orderSubtitle(row: any) {
    const parts = [];
    if (row?.customer_name) parts.push(row.customer_name);
    if (row?.order_type) parts.push(productionTypeLabel(row.order_type, t));
    return parts.join(" · ");
  }

  async function refreshPackages() {
    await Promise.all([mutate(), mutatePendingRequests()]);
  }

  async function openEdit(pkg: any) {
    setMessage("");
    setError("");
    setEditing(pkg);
    setEditLoading(true);
    setEditForm(null);
    try {
      const detail = await api.get<any>(`/api/packages/${pkg.id}`);
      setEditForm({
        color: String(detail.color || ""),
        package_type: String(detail.package_type || "bag"),
        capacity: String(detail.capacity || 60),
        weight_kg: detail.weight_kg == null ? "" : String(detail.weight_kg),
        warehouse_id: detail.warehouse_id == null ? "" : String(detail.warehouse_id),
        storage_cell: String(detail.storage_cell || ""),
        storage_shelf: String(detail.storage_shelf || ""),
        notes: String(detail.notes || ""),
        reason: "",
        items: (detail.items || []).map((item: any) => ({
          model_id: Number(item.model_id || detail.model_id),
          color: String(item.color || detail.color || ""),
          size: String(item.size || ""),
          quantity: String(item.quantity || 0),
        })),
        batch_allocations: (detail.batch_allocations || []).map((row: any) => ({
          production_batch_id: Number(row.production_batch_id),
          quantity: String(row.quantity || 0),
        })),
      });
    } catch (err: any) {
      setError(err?.message || t("page.packages.editLoadError"));
    } finally {
      setEditLoading(false);
    }
  }

  async function submitEditRequest(e: FormEvent) {
    e.preventDefault();
    if (!editing || !editForm) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const payload: any = {
        color: editForm.color.trim(),
        package_type: editForm.package_type.trim() || "bag",
        capacity: Number(editForm.capacity || 0),
        weight_kg: editForm.weight_kg === "" ? null : Number(editForm.weight_kg),
        warehouse_id: editForm.warehouse_id === "" ? null : Number(editForm.warehouse_id),
        storage_cell: editForm.storage_cell.trim() || null,
        storage_shelf: editForm.storage_shelf.trim() || null,
        notes: editForm.notes,
        items: editForm.items.map((item) => ({
          model_id: item.model_id,
          color: editForm.color.trim(),
          size: item.size.trim(),
          quantity: Number(item.quantity || 0),
        })),
      };
      if (editForm.batch_allocations.length > 1) {
        payload.batch_allocations = editForm.batch_allocations.map((row) => ({
          production_batch_id: row.production_batch_id,
          quantity: Number(row.quantity || 0),
        }));
      }
      await api.post(`/api/packages/${editing.id}/change-requests`, {
        request_type: "edit",
        reason: editForm.reason.trim() || undefined,
        payload,
      });
      setEditing(null);
      setEditForm(null);
      setMessage(t("page.packages.editRequestSent"));
      await refreshPackages();
    } catch (err: any) {
      setError(err?.message || t("page.packages.editRequestFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function submitDeleteRequest() {
    if (!deleting) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.post(`/api/packages/${deleting.id}/change-requests`, { request_type: "delete" });
      setDeleting(null);
      setMessage(t("page.packages.deleteRequestSent"));
      await refreshPackages();
    } catch (err: any) {
      setError(err?.message || t("page.packages.deleteRequestFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function approveRequest(req: any) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.post(`/api/packages/change-requests/${req.id}/approve`);
      setMessage(t("page.packages.requestApproved"));
      await refreshPackages();
    } catch (err: any) {
      setError(err?.message || t("page.packages.requestApproveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function rejectRequest(req: any) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.post(`/api/packages/change-requests/${req.id}/reject`);
      setMessage(t("page.packages.requestRejected"));
      await refreshPackages();
    } catch (err: any) {
      setError(err?.message || t("page.packages.requestRejectFailed"));
    } finally {
      setBusy(false);
    }
  }

  function setItemField(index: number, field: "size" | "quantity", value: string) {
    setEditForm((prev) => {
      if (!prev) return prev;
      const items = [...prev.items];
      items[index] = { ...items[index], [field]: value };
      return { ...prev, items };
    });
  }

  function addItemRow() {
    setEditForm((prev) => {
      if (!prev || !editing) return prev;
      return {
        ...prev,
        items: [...prev.items, { model_id: Number(editing.model_id), color: prev.color, size: "", quantity: "1" }],
      };
    });
  }

  function removeItemRow(index: number) {
    setEditForm((prev) => {
      if (!prev || prev.items.length <= 1) return prev;
      return { ...prev, items: prev.items.filter((_, idx) => idx !== index) };
    });
  }

  function setBatchQuantity(index: number, value: string) {
    setEditForm((prev) => {
      if (!prev) return prev;
      const rows = [...prev.batch_allocations];
      rows[index] = { ...rows[index], quantity: value };
      return { ...prev, batch_allocations: rows };
    });
  }

  return (
    <div>
      <PageHeader title={`${factoryLabel} - ${t("page.packages.title")}`} subtitle={t("page.packages.subtitle")} actions={<Link href={`/packaging/receive?packaging_department=${packagingDepartment}`} className="btn">{t("nav.receiveFromSewing")}</Link>} />
      {message && <div className="mb-3 rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">{message}</div>}
      {error && <div className="mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      <div className="card overflow-x-auto">
        <table className="table">
          <thead>
            <tr>
              <th>{t("field.packageNo")}</th>
              <th>{t("field.order")}</th>
              <th>{t("field.barcode")}</th>
              <th>{t("field.model")}</th>
              <th>{t("field.color")}</th>
              <th>{t("field.totalQty")}</th>
              <th>{t("field.cell")}</th>
              <th>{t("field.shelf")}</th>
              <th>{t("common.status")}</th>
              <th>{t("field.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const first = g.packages[0];
              const last = g.packages[g.packages.length - 1];
              const statusVariants = Array.from(new Set(g.packages.map((p) => String(p.status || ""))));
              const sameModel = g.packages.every((p) => p.model_id === first.model_id);
              const sameColor = g.packages.every((p) => p.color === first.color);
              const sameStatus = statusVariants.length === 1;
              const sameCell = g.packages.every((p) => String(p.storage_cell || "") === String(first.storage_cell || ""));
              const sameShelf = g.packages.every((p) => String(p.storage_shelf || "") === String(first.storage_shelf || ""));
              const packageIds = g.packages.map((p) => p.id).join(",");
              const isExpanded = !!expandedGroups[g.key];
              const groupLabel = orderTitle(first);
              const groupMeta = orderSubtitle(first);

              return (
                <Fragment key={g.key}>
                  <tr>
                    <td className="font-medium">
                      <div>{g.packages.length === 1 ? first.package_no : `${first.package_no} - ${last.package_no}`}</div>
                      <div className="text-xs text-slate-500">
                        {g.packages.length} {t("field.packages")}
                      </div>
                    </td>
                    <td>
                      <div className="font-medium text-slate-900">{groupLabel}</div>
                      {groupMeta && <div className="text-xs text-slate-500">{groupMeta}</div>}
                    </td>
                    <td><code>{g.packages.length}</code></td>
                    <td>{sameModel ? first.model_id : "-"}</td>
                    <td>{sameColor ? first.color : "-"}</td>
                    <td>{g.total_quantity}</td>
                    <td>{sameCell ? (first.storage_cell || "-") : "-"}</td>
                    <td>{sameShelf ? (first.storage_shelf || "-") : "-"}</td>
                    <td>
                      <span className="badge">
                        {sameStatus ? statusLabel(first.status, t) : `${statusLabel(first.status, t)} +${statusVariants.length - 1}`}
                      </span>
                    </td>
                    <td className="flex gap-2">
                      <button
                        type="button"
                        className="text-brand-600 hover:underline"
                        onClick={() => setExpandedGroups((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
                      >
                        {isExpanded ? t("common.close") : t("btn.open")}
                      </button>
                      {g.packages.length > 1 && (
                        <button
                          type="button"
                          className="text-slate-600 hover:underline"
                          onClick={() => api.openLabel(`/api/packages/label-sheet/by-ids?ids=${encodeURIComponent(packageIds)}`)}
                        >
                          {t("btn.print")}
                        </button>
                      )}
                    </td>
                  </tr>
                  {isExpanded && g.packages.map((p) => {
                    const pending = pendingByPackage.get(Number(p.id));
                    return (
                      <tr key={p.id} className="bg-slate-50">
                        <td className="font-medium">
                          <div>{p.package_no}</div>
                          {pending && (
                            <div className="mt-1 text-xs text-amber-700">
                              {pending.request_type === "delete" ? t("page.packages.pendingDelete") : t("page.packages.pendingEdit")}
                            </div>
                          )}
                        </td>
                        <td>
                          <div className="font-medium text-slate-900">{orderTitle(p)}</div>
                          {orderSubtitle(p) && <div className="text-xs text-slate-500">{orderSubtitle(p)}</div>}
                        </td>
                        <td><code>{p.barcode}</code></td>
                        <td>{p.model_id}</td>
                        <td>{p.color}</td>
                        <td>{p.total_quantity}</td>
                        <td>{p.storage_cell || "-"}</td>
                        <td>{p.storage_shelf || "-"}</td>
                        <td><span className="badge">{statusLabel(p.status, t)}</span></td>
                        <td className="flex flex-wrap gap-2">
                          <Link href={`/packages/${p.id}`} className="text-brand-600 hover:underline">{t("btn.view")}</Link>
                          {canTraceability && (
                            <Link href={`/traceability?package=${encodeURIComponent(p.package_no || p.barcode || p.id)}`} className="text-brand-600 hover:underline">
                              {t("page.traceability.passport")}
                            </Link>
                          )}
                          <button type="button" className="text-slate-600 hover:underline" onClick={() => api.openLabel(`/api/packages/${p.id}/label`)}>{t("btn.label")}</button>
                          <button type="button" className="text-blue-700 hover:underline disabled:text-slate-400 disabled:no-underline" disabled={!!pending || busy} onClick={() => openEdit(p)}>{t("common.edit")}</button>
                          <button type="button" className="text-red-700 hover:underline disabled:text-slate-400 disabled:no-underline" disabled={!!pending || busy} onClick={() => setDeleting(p)}>{t("common.delete")}</button>
                          {pending && canApprovePackageChange && (
                            <>
                              <button type="button" className="text-green-700 hover:underline disabled:text-slate-400" disabled={busy} onClick={() => approveRequest(pending)}>{t("btn.approve")}</button>
                              <button type="button" className="text-slate-600 hover:underline disabled:text-slate-400" disabled={busy} onClick={() => rejectRequest(pending)}>{t("btn.reject")}</button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </Fragment>
              );
            })}
            {groups.length === 0 && (
              <tr>
                <td colSpan={10} className="text-sm text-slate-400">
                  {data ? t("page.packages.empty") : t("common.loading")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={Number(pageData?.total || data.length)}
          count={data.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
        />
      </div>
      <Modal
        open={!!editing}
        onClose={() => { if (!busy) { setEditing(null); setEditForm(null); } }}
        title={editing ? t("page.packages.editTitle", { package: editing.package_no }) : ""}
        wide
      >
        {editLoading && <div className="text-sm text-slate-500">{t("common.loading")}</div>}
        {!editLoading && editForm && (
          <form className="space-y-4" onSubmit={submitEditRequest}>
            <div className="grid gap-3 md:grid-cols-3">
              <div>
                <label className="label">{t("common.color")}</label>
                <input className="input" value={editForm.color} onChange={(e) => setEditForm({ ...editForm, color: e.target.value })} required />
              </div>
              <div>
                <label className="label">{t("field.packageType")}</label>
                <input className="input" value={editForm.package_type} onChange={(e) => setEditForm({ ...editForm, package_type: e.target.value })} required />
              </div>
              <div>
                <label className="label">{t("field.capacity")}</label>
                <input className="input" type="number" min={1} value={editForm.capacity} onChange={(e) => setEditForm({ ...editForm, capacity: e.target.value })} required />
              </div>
              <div>
                <label className="label">{t("field.weightKg")}</label>
                <input className="input" type="number" min={0} step="0.001" value={editForm.weight_kg} onChange={(e) => setEditForm({ ...editForm, weight_kg: e.target.value })} />
              </div>
              <div>
                <label className="label">{t("field.cell")}</label>
                <input className="input" value={editForm.storage_cell} onChange={(e) => setEditForm({ ...editForm, storage_cell: e.target.value })} />
              </div>
              <div>
                <label className="label">{t("field.shelf")}</label>
                <input className="input" value={editForm.storage_shelf} onChange={(e) => setEditForm({ ...editForm, storage_shelf: e.target.value })} />
              </div>
            </div>

            <div>
              <div className="mb-2 flex items-center justify-between">
                <div className="text-sm font-medium text-slate-900">{t("page.packaging.sizesInPackage")}</div>
                <button type="button" className="text-sm text-brand-600 hover:underline" onClick={addItemRow}>{t("common.add")}</button>
              </div>
              <div className="space-y-2">
                {editForm.items.map((item, idx) => (
                  <div key={`${idx}-${item.size}`} className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_110px_auto]">
                    <input className="input" value={item.size} onChange={(e) => setItemField(idx, "size", e.target.value)} placeholder={t("common.size")} required />
                    <input className="input" type="number" min={1} value={item.quantity} onChange={(e) => setItemField(idx, "quantity", e.target.value)} required />
                    <button type="button" className="btn" onClick={() => removeItemRow(idx)} disabled={editForm.items.length <= 1}>{t("common.remove")}</button>
                  </div>
                ))}
              </div>
              <div className="mt-2 text-sm text-slate-500">{t("common.total")}: {editTotal}</div>
            </div>

            {editForm.batch_allocations.length > 1 && (
              <div>
                <div className="mb-2 text-sm font-medium text-slate-900">{t("page.packages.batchAllocations")}</div>
                <div className="space-y-2">
                  {editForm.batch_allocations.map((row, idx) => (
                    <div key={row.production_batch_id} className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_120px]">
                      <div className="input flex items-center bg-slate-50 text-slate-600">#{row.production_batch_id}</div>
                      <input className="input" type="number" min={1} value={row.quantity} onChange={(e) => setBatchQuantity(idx, e.target.value)} required />
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <label className="label">{t("common.notes")}</label>
              <textarea className="input min-h-20" value={editForm.notes} onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })} />
            </div>
            <div>
              <label className="label">{t("field.reason")}</label>
              <textarea className="input min-h-20" value={editForm.reason} onChange={(e) => setEditForm({ ...editForm, reason: e.target.value })} />
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn" onClick={() => { setEditing(null); setEditForm(null); }} disabled={busy}>{t("common.cancel")}</button>
              <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? t("common.saving") : t("page.packages.requestApproval")}</button>
            </div>
          </form>
        )}
      </Modal>
      <ConfirmDialog
        isOpen={!!deleting}
        title={t("page.packages.deleteTitle")}
        message={deleting ? t("page.packages.deleteMessage", { package: deleting.package_no }) : ""}
        confirmText={t("page.packages.requestDelete")}
        onConfirm={submitDeleteRequest}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
