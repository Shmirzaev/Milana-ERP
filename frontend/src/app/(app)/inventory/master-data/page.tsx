"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Edit3, Plus, Search, Trash2, X } from "lucide-react";
import PageHeader from "@/components/PageHeader";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { useDialogs } from "@/components/DialogProvider";
import { compositionTotal, formatComposition, type MaterialComposition } from "@/lib/materialComposition";

type TabKey = "materials" | "accessories" | "suppliers";

type Item = {
  id: number;
  sku: string;
  name: string;
  category: string;
  unit: string;
  default_cost: number;
  reorder_level: number;
  track_batch: boolean;
  is_active: boolean;
  image_url?: string | null;
  composition?: MaterialComposition[] | null;
};

type Supplier = {
  id: number;
  name: string;
  phone?: string | null;
  email?: string | null;
  address?: string | null;
  notes?: string | null;
};

type ItemForm = {
  id?: number;
  sku: string;
  name: string;
  category: string;
  unit: string;
  default_cost: string;
  reorder_level: string;
  track_batch: boolean;
  is_active: boolean;
  image_url: string;
  composition: Array<{ name: string; percentage: string }>;
};

type SupplierForm = {
  id?: number;
  name: string;
  phone: string;
  email: string;
  address: string;
  notes: string;
};

const ACCESSORY_CATEGORIES = ["accessory", "packaging"];

const EMPTY_MATERIAL: ItemForm = {
  sku: "",
  name: "",
  category: "fabric",
  unit: "kg",
  default_cost: "0",
  reorder_level: "0",
  track_batch: true,
  is_active: true,
  image_url: "",
  composition: [{ name: "", percentage: "" }],
};

const EMPTY_ACCESSORY: ItemForm = {
  ...EMPTY_MATERIAL,
  category: "accessory",
  unit: "pcs",
};

const EMPTY_SUPPLIER: SupplierForm = {
  name: "",
  phone: "",
  email: "",
  address: "",
  notes: "",
};

function itemToForm(item: Item): ItemForm {
  return {
    id: item.id,
    sku: item.sku,
    name: item.name,
    category: item.category,
    unit: item.unit,
    default_cost: String(Number(item.default_cost || 0)),
    reorder_level: String(Number(item.reorder_level || 0)),
    track_batch: Boolean(item.track_batch),
    is_active: Boolean(item.is_active),
    image_url: item.image_url || "",
    composition: (item.composition || []).length
      ? (item.composition || []).map((row) => ({
          name: String(row.name || ""),
          percentage: String(Number(row.percentage || 0)),
        }))
      : [{ name: "", percentage: "" }],
  };
}

function supplierToForm(supplier: Supplier): SupplierForm {
  return {
    id: supplier.id,
    name: supplier.name || "",
    phone: supplier.phone || "",
    email: supplier.email || "",
    address: supplier.address || "",
    notes: supplier.notes || "",
  };
}

function itemPayload(form: ItemForm) {
  return {
    sku: form.sku.trim() || generatedItemSku(form),
    name: form.name.trim(),
    category: form.category,
    unit: form.unit.trim(),
    default_cost: Number(form.default_cost || 0),
    reorder_level: Number(form.reorder_level || 0),
    track_batch: form.track_batch,
    is_active: form.is_active,
    image_url: form.image_url.trim() || null,
    composition: form.composition
      .map((row) => ({ name: row.name.trim(), percentage: Number(row.percentage || 0) }))
      .filter((row) => row.name && Number.isFinite(row.percentage) && row.percentage > 0),
  };
}

function generatedItemSku(form: ItemForm) {
  const prefix = ACCESSORY_CATEGORIES.includes(form.category) ? "ACC" : "MAT";
  const namePart = form.name
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 24) || "ITEM";
  return `${prefix}-${namePart}-${Date.now().toString(36).toUpperCase()}`;
}

function supplierPayload(form: SupplierForm) {
  return {
    name: form.name.trim(),
    phone: form.phone.trim() || null,
    email: form.email.trim() || null,
    address: form.address.trim() || null,
    notes: form.notes.trim() || null,
  };
}

function lc(value: unknown) {
  return String(value || "").toLowerCase();
}

export default function InventoryMasterDataPage() {
  const { t } = useT();
  const dialogs = useDialogs();
  const { me } = useMe();
  const [tab, setTab] = useState<TabKey>("materials");
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [itemForm, setItemForm] = useState<ItemForm>(EMPTY_MATERIAL);
  const [supplierForm, setSupplierForm] = useState<SupplierForm>(EMPTY_SUPPLIER);
  const [saving, setSaving] = useState(false);
  const canEditItems = can(me, "storage.items", "*");
  const canEditSuppliers = can(me, "storage.suppliers", "*");
  const canView = canEditItems || canEditSuppliers;
  const availableTabs = useMemo<TabKey[]>(() => {
    const tabs: TabKey[] = [];
    if (canEditItems) tabs.push("materials", "accessories");
    if (canEditSuppliers) tabs.push("suppliers");
    return tabs;
  }, [canEditItems, canEditSuppliers]);

  const { data: materials, mutate: refreshMaterials } = useSWR<Item[]>(
    canEditItems ? "/api/inventory/items?group=materials&page_size=500" : null,
    fetcher,
  );
  const { data: accessories, mutate: refreshAccessories } = useSWR<Item[]>(
    canEditItems ? "/api/inventory/items?group=accessories&page_size=500" : null,
    fetcher,
  );
  const { data: suppliers, mutate: refreshSuppliers } = useSWR<Supplier[]>(
    canEditSuppliers ? "/api/suppliers" : null,
    fetcher,
  );

  const activeItems = useMemo(
    () => (tab === "materials" ? materials || [] : tab === "accessories" ? accessories || [] : []),
    [accessories, materials, tab],
  );
  const filteredItems = useMemo(
    () => activeItems.filter((item) => !query.trim() || [item.name, formatComposition(item.composition)].some((value) => lc(value).includes(lc(query)))),
    [activeItems, query],
  );
  const filteredSuppliers = useMemo(
    () => (suppliers || []).filter((supplier) => !query.trim() || [supplier.name, supplier.phone, supplier.email, supplier.address].some((value) => lc(value).includes(lc(query)))),
    [query, suppliers],
  );
  const isSupplierTab = tab === "suppliers";
  const canEditActive = isSupplierTab ? canEditSuppliers : canEditItems;
  const compositionPercent = compositionTotal(itemForm.composition.map((row) => ({ name: row.name, percentage: Number(row.percentage || 0) })));
  const compositionOverLimit = compositionPercent > 100.0001;

  useEffect(() => {
    if (!availableTabs.length || availableTabs.includes(tab)) return;
    const next = availableTabs[0];
    setTab(next);
    setQuery("");
    setMessage("");
    setItemForm(next === "accessories" ? EMPTY_ACCESSORY : EMPTY_MATERIAL);
    setSupplierForm(EMPTY_SUPPLIER);
  }, [availableTabs, tab]);

  function switchTab(next: TabKey) {
    setTab(next);
    setQuery("");
    setMessage("");
    setItemForm(next === "accessories" ? EMPTY_ACCESSORY : EMPTY_MATERIAL);
    setSupplierForm(EMPTY_SUPPLIER);
  }

  function resetItemForm() {
    setItemForm(tab === "accessories" ? EMPTY_ACCESSORY : EMPTY_MATERIAL);
  }

  function updateCompositionRow(index: number, patch: Partial<{ name: string; percentage: string }>) {
    setItemForm((current) => ({
      ...current,
      composition: current.composition.map((row, rowIndex) => rowIndex === index ? { ...row, ...patch } : row),
    }));
  }

  function addCompositionRow() {
    setItemForm((current) => ({
      ...current,
      composition: [...current.composition, { name: "", percentage: "" }],
    }));
  }

  function removeCompositionRow(index: number) {
    setItemForm((current) => {
      const nextRows = current.composition.filter((_, rowIndex) => rowIndex !== index);
      return { ...current, composition: nextRows.length ? nextRows : [{ name: "", percentage: "" }] };
    });
  }

  async function submitItem(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEditItems) return;
    setSaving(true);
    setMessage("");
    try {
      if (compositionOverLimit) {
        setMessage(t("page.masterData.compositionOverLimit"));
        return;
      }
      const payload = itemPayload(itemForm);
      if (itemForm.id) {
        await api.patch(`/api/inventory/items/${itemForm.id}`, payload);
        setMessage(t("page.masterData.itemUpdated"));
      } else {
        await api.post("/api/inventory/items", payload);
        setMessage(t("page.masterData.itemCreated"));
      }
      resetItemForm();
      refreshMaterials();
      refreshAccessories();
    } catch (error: any) {
      setMessage(error?.message || t("page.masterData.actionFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteItem(item: Item) {
    if (!canEditItems) return;
    if (!(await dialogs.ask({ message: t("page.masterData.deleteItemConfirm", { name: item.name }), tone: "danger" }))) return;
    setMessage("");
    try {
      await api.del(`/api/inventory/items/${item.id}?force=true`);
      setMessage(t("page.masterData.itemDeleted"));
      refreshMaterials();
      refreshAccessories();
      if (itemForm.id === item.id) resetItemForm();
    } catch (error: any) {
      setMessage(error?.message || t("page.masterData.deleteBlocked"));
    }
  }

  async function submitSupplier(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEditSuppliers) return;
    setSaving(true);
    setMessage("");
    try {
      const payload = supplierPayload(supplierForm);
      if (supplierForm.id) {
        await api.patch(`/api/suppliers/${supplierForm.id}`, payload);
        setMessage(t("page.masterData.supplierUpdated"));
      } else {
        await api.post("/api/suppliers", payload);
        setMessage(t("page.masterData.supplierCreated"));
      }
      setSupplierForm(EMPTY_SUPPLIER);
      refreshSuppliers();
    } catch (error: any) {
      setMessage(error?.message || t("page.masterData.actionFailed"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteSupplier(supplier: Supplier) {
    if (!canEditSuppliers) return;
    if (!(await dialogs.ask({ message: t("page.masterData.deleteSupplierConfirm", { name: supplier.name }), tone: "danger" }))) return;
    setMessage("");
    try {
      await api.del(`/api/suppliers/${supplier.id}`);
      setMessage(t("page.masterData.supplierDeleted"));
      refreshSuppliers();
      if (supplierForm.id === supplier.id) setSupplierForm(EMPTY_SUPPLIER);
    } catch (error: any) {
      setMessage(error?.message || t("page.masterData.deleteBlocked"));
    }
  }

  if (!canView) {
    return <PageHeader title={t("page.masterData.title")} subtitle={t("page.masterData.noAccess")} />;
  }

  return (
    <div>
      <PageHeader title={t("page.masterData.title")} subtitle={t("page.masterData.subtitle")} />

      <div className="mb-4 flex flex-wrap gap-2">
        {availableTabs.map((key) => (
          <button
            key={key}
            type="button"
            className={`rounded-md border px-3 py-2 text-sm font-medium transition ${
              tab === key
                ? "border-[#14110b] bg-[#14110b] text-[#fdfcf8]"
                : "border-[#ded8c8] bg-[#fdfcf8] text-[#56503f] hover:border-[#bcb39f] hover:text-[#14110b]"
            }`}
            onClick={() => switchTab(key)}
          >
            {key === "materials" ? t("page.masterData.materials") : key === "accessories" ? t("page.masterData.accessories") : t("page.masterData.suppliers")}
          </button>
        ))}
      </div>

      {message && <div className="mb-4 rounded-md border border-[#ded9ca] bg-[#fbfaf6] px-4 py-3 text-sm text-[#56503f]">{message}</div>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="card overflow-hidden">
          <div className="border-b border-[#ecebe3] p-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <h2 className="app-card-title">
                {isSupplierTab ? t("page.masterData.suppliers") : tab === "materials" ? t("page.masterData.materials") : t("page.masterData.accessories")}
              </h2>
              <div className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-[#ded9ca] bg-[#fdfcf8] px-3 md:w-80">
                <Search className="h-4 w-4 shrink-0 text-[#8a8472]" />
                <input
                  className="w-full min-w-0 bg-transparent text-sm text-[#14110b] placeholder:text-[#8a8472] focus:outline-none"
                  placeholder={t("common.search")}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
                {query && (
                  <button type="button" className="icon-btn" onClick={() => setQuery("")} aria-label={t("common.clear")}>
                    <X />
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="overflow-x-auto">
            {isSupplierTab ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("common.name")}</th>
                    <th>{t("field.phone")}</th>
                    <th>{t("field.email")}</th>
                    <th>{t("field.address")}</th>
                    {canEditActive && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {filteredSuppliers.map((supplier) => (
                    <tr key={supplier.id}>
                      <td className="font-medium text-[#14110b]">{supplier.name}</td>
                      <td>{supplier.phone || "-"}</td>
                      <td>{supplier.email || "-"}</td>
                      <td>{supplier.address || "-"}</td>
                      {canEditActive && (
                        <td>
                          <div className="flex justify-end gap-2">
                            <button type="button" className="icon-btn" onClick={() => setSupplierForm(supplierToForm(supplier))} title={t("btn.edit")}>
                              <Edit3 />
                            </button>
                            <button type="button" className="icon-btn text-red-700" onClick={() => deleteSupplier(supplier)} title={t("btn.delete")}>
                              <Trash2 />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                  {filteredSuppliers.length === 0 && (
                    <tr><td colSpan={canEditActive ? 5 : 4} className="text-sm text-slate-400">{t("page.masterData.noSuppliers")}</td></tr>
                  )}
                </tbody>
              </table>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>{t("common.name")}</th>
                    {tab === "materials" && <th>{t("field.composition")}</th>}
                    {canEditActive && <th></th>}
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.map((item) => (
                    <tr key={item.id}>
                      <td>{item.name}</td>
                      {tab === "materials" && (
                        <td className="max-w-[280px] text-xs text-[#56503f]">
                          {formatComposition(item.composition) || "-"}
                        </td>
                      )}
                      {canEditActive && (
                        <td>
                          <div className="flex justify-end gap-2">
                            <button type="button" className="icon-btn" onClick={() => setItemForm(itemToForm(item))} title={t("btn.edit")}>
                              <Edit3 />
                            </button>
                            <button type="button" className="icon-btn text-red-700" onClick={() => deleteItem(item)} title={t("btn.delete")}>
                              <Trash2 />
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                  {filteredItems.length === 0 && (
                    <tr><td colSpan={(canEditActive ? 2 : 1) + (tab === "materials" ? 1 : 0)} className="text-sm text-slate-400">{t("page.masterData.noItems")}</td></tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section className="card p-5">
          {isSupplierTab ? (
            <form onSubmit={submitSupplier} className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="app-card-title">{supplierForm.id ? t("page.masterData.editSupplier") : t("page.masterData.newSupplier")}</h2>
                {supplierForm.id && (
                  <button type="button" className="icon-btn" onClick={() => setSupplierForm(EMPTY_SUPPLIER)} aria-label={t("common.clear")}>
                    <X />
                  </button>
                )}
              </div>
              <div>
                <label className="label">{t("common.name")}</label>
                <input className="input" value={supplierForm.name} onChange={(event) => setSupplierForm({ ...supplierForm, name: event.target.value })} required />
              </div>
              <div>
                <label className="label">{t("field.phone")}</label>
                <input className="input" value={supplierForm.phone} onChange={(event) => setSupplierForm({ ...supplierForm, phone: event.target.value })} />
              </div>
              <div>
                <label className="label">{t("field.email")}</label>
                <input className="input" type="email" value={supplierForm.email} onChange={(event) => setSupplierForm({ ...supplierForm, email: event.target.value })} />
              </div>
              <div>
                <label className="label">{t("field.address")}</label>
                <textarea className="input min-h-20" value={supplierForm.address} onChange={(event) => setSupplierForm({ ...supplierForm, address: event.target.value })} />
              </div>
              <div>
                <label className="label">{t("field.notes")}</label>
                <textarea className="input min-h-20" value={supplierForm.notes} onChange={(event) => setSupplierForm({ ...supplierForm, notes: event.target.value })} />
              </div>
              <button className="btn btn-primary w-full justify-center" disabled={saving || !canEditActive}>
                <Plus className="h-4 w-4" />
                {saving ? t("common.saving") : supplierForm.id ? t("btn.save") : t("btn.create")}
              </button>
            </form>
          ) : (
            <form onSubmit={submitItem} className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h2 className="app-card-title">{itemForm.id ? t("page.masterData.editItem") : t("page.masterData.newItem")}</h2>
                {itemForm.id && (
                  <button type="button" className="icon-btn" onClick={resetItemForm} aria-label={t("common.clear")}>
                    <X />
                  </button>
                )}
              </div>
              <div>
                <label className="label">{t("common.name")}</label>
                <input className="input" value={itemForm.name} onChange={(event) => setItemForm({ ...itemForm, name: event.target.value })} required />
              </div>
              {tab === "materials" && (
                <div className="space-y-2 rounded-md border border-[#ecebe3] bg-[#fbfaf6] p-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-[#14110b]">{t("field.composition")}</div>
                      <div className={`text-xs ${compositionOverLimit ? "text-red-700" : "text-[#8a8472]"}`}>
                        {t("page.masterData.compositionTotal", { total: Number(compositionPercent.toFixed(2)) })}
                      </div>
                    </div>
                    <button type="button" className="btn h-8 px-2 text-xs" onClick={addCompositionRow}>
                      <Plus className="h-3.5 w-3.5" />
                      {t("page.masterData.addCompositionRow")}
                    </button>
                  </div>
                  <div className="space-y-2">
                    {itemForm.composition.map((row, index) => (
                      <div key={index} className="grid grid-cols-[minmax(0,1fr)_96px_32px] gap-2">
                        <input
                          className="input"
                          placeholder={t("page.masterData.compositionName")}
                          value={row.name}
                          onChange={(event) => updateCompositionRow(index, { name: event.target.value })}
                        />
                        <input
                          className="input"
                          type="number"
                          min={0}
                          max={100}
                          step="0.01"
                          placeholder="%"
                          value={row.percentage}
                          onChange={(event) => updateCompositionRow(index, { percentage: event.target.value })}
                        />
                        <button
                          type="button"
                          className="icon-btn"
                          onClick={() => removeCompositionRow(index)}
                          title={t("common.remove")}
                          aria-label={t("common.remove")}
                        >
                          <Trash2 />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <button className="btn btn-primary w-full justify-center" disabled={saving || !canEditActive || compositionOverLimit}>
                <Plus className="h-4 w-4" />
                {saving ? t("common.saving") : itemForm.id ? t("btn.save") : t("btn.create")}
              </button>
            </form>
          )}
        </section>
      </div>
    </div>
  );
}
