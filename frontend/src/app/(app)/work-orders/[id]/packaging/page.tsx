"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function PackagingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data: wo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(po?.model_id ? `/api/models/${po.model_id}` : null, fetcher);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);

  const [rec, setRec] = useState({ input_qty: 0, packed_qty: 0, damaged_qty: 0, packaging_material_used: "", notes: "" });
  const [pkgItems, setPkgItems] = useState<{ size: string; quantity: number }[]>([{ size: "M", quantity: 60 }]);
  const [overrideCap, setOverrideCap] = useState(false);
  const [capacity, setCapacity] = useState(60);
  const [color, setColor] = useState("white");
  const [copies, setCopies] = useState(1);
  const [copiesTouched, setCopiesTouched] = useState(false);
  const [recMsg, setRecMsg] = useState("");
  const [pkgNotice, setPkgNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [pkg, setPkg] = useState<any>(null);

  const colorOrderItems = useMemo(() => {
    const allItems = po?.items || [];
    const rows = allItems.filter((it: any) => String(it?.color || "").toLowerCase() === String(color || "").toLowerCase());
    const source = rows.length > 0 ? rows : allItems;
    const bySize = new Map<string, number>();
    for (const it of source) {
      const size = String(it?.size || "-").trim();
      if (!size || size === "-") continue;
      bySize.set(size, (bySize.get(size) || 0) + Math.max(0, Number(it?.planned_quantity || 0)));
    }
    return Array.from(bySize.entries()).map(([size, planned_quantity]) => ({ size, planned_quantity }));
  }, [po?.items, color]);

  const totalColorQty = useMemo(
    () => colorOrderItems.reduce((s: number, it: any) => s + Number(it?.planned_quantity || 0), 0),
    [colorOrderItems],
  );

  const suggestedCopies = useMemo(() => {
    const cap = Math.max(1, Number(capacity || 0));
    return totalColorQty > 0 ? Math.max(1, Math.ceil(totalColorQty / cap)) : 1;
  }, [totalColorQty, capacity]);

  const autoPackageItems = useMemo(() => {
    const cap = Math.max(1, Number(capacity || 0));
    const rows = colorOrderItems
      .map((it: any) => ({ size: String(it?.size || "-"), qty: Math.max(0, Number(it?.planned_quantity || 0)) }))
      .filter((it: any) => it.size && it.size !== "-");
    if (!rows.length) return [{ size: "M", quantity: cap }];

    const n = rows.length;
    const total = rows.reduce((s: number, r: any) => s + r.qty, 0);
    const out = rows.map((r: any) => ({ size: r.size, quantity: 0, _weight: r.qty }));

    if (cap >= n) {
      for (const o of out) o.quantity = 1;
      let remaining = cap - n;
      if (remaining > 0) {
        if (total > 0) {
          const shares = out.map((o) => ({
            size: o.size,
            base: Math.floor((remaining * o._weight) / total),
            rem: ((remaining * o._weight) / total) - Math.floor((remaining * o._weight) / total),
          }));
          let used = 0;
          for (const o of out) {
            const sh = shares.find((s) => s.size === o.size)!;
            o.quantity += sh.base;
            used += sh.base;
          }
          let left = remaining - used;
          const ranked = [...shares].sort((a, b) => b.rem - a.rem);
          let idx = 0;
          while (left > 0) {
            const target = ranked[idx % ranked.length];
            const o = out.find((x) => x.size === target.size)!;
            o.quantity += 1;
            left -= 1;
            idx += 1;
          }
        } else {
          let i = 0;
          while (remaining > 0) {
            out[i % out.length].quantity += 1;
            remaining -= 1;
            i += 1;
          }
        }
      }
    } else {
      const ranked = [...out].sort((a, b) => b._weight - a._weight);
      for (let i = 0; i < cap; i += 1) ranked[i].quantity += 1;
    }

    return out.map(({ size, quantity }) => ({ size, quantity }));
  }, [colorOrderItems, capacity]);

  const packingPreview = useMemo(() => {
    const perPackage = pkgItems
      .map((it) => ({ size: String(it.size || "").trim(), qty: Math.max(0, Number(it.quantity || 0)) }))
      .filter((it) => it.size && it.qty > 0);
    const perPackageMap = new Map<string, number>();
    for (const it of perPackage) perPackageMap.set(it.size, (perPackageMap.get(it.size) || 0) + it.qty);

    const demandMap = new Map<string, number>();
    for (const it of colorOrderItems) demandMap.set(String(it.size || ""), Math.max(0, Number(it.planned_quantity || 0)));

    const packageTotal = perPackage.reduce((s, it) => s + it.qty, 0);
    if (perPackage.length === 0 || packageTotal <= 0) {
      return { fullCount: 0, notFullCount: 0, packageTotal: 0, partialPackages: [] as Array<{ index: number; items: Array<{ size: string; qty: number }>; total: number }> };
    }

    let fullByRecipe = Number.POSITIVE_INFINITY;
    for (const it of perPackage) {
      const demand = demandMap.get(it.size) || 0;
      fullByRecipe = Math.min(fullByRecipe, Math.floor(demand / it.qty));
    }
    if (!Number.isFinite(fullByRecipe)) fullByRecipe = 0;

    const targetCopies = Math.max(1, Number(copies || 1));
    const fullCount = Math.max(0, Math.min(targetCopies, fullByRecipe));

    const remainingMap = new Map<string, number>();
    for (const [size, demand] of demandMap.entries()) {
      const used = (perPackageMap.get(size) || 0) * fullCount;
      remainingMap.set(size, Math.max(0, demand - used));
    }
    const remainingTotal = Array.from(remainingMap.values()).reduce((a, b) => a + b, 0);
    const partialFromDemand = remainingTotal > 0 ? Math.ceil(remainingTotal / packageTotal) : 0;
    const extraEmpty = Math.max(0, targetCopies - fullCount - partialFromDemand);

    const partialPackages: Array<{ index: number; items: Array<{ size: string; qty: number }>; total: number }> = [];
    for (let p = 0; p < partialFromDemand; p += 1) {
      let capLeft = packageTotal;
      const packItems: Array<{ size: string; qty: number }> = [];

      for (const it of perPackage) {
        if (capLeft <= 0) break;
        const rem = remainingMap.get(it.size) || 0;
        const take = Math.min(rem, it.qty, capLeft);
        if (take > 0) {
          packItems.push({ size: it.size, qty: take });
          remainingMap.set(it.size, rem - take);
          capLeft -= take;
        }
      }

      if (capLeft > 0) {
        let progress = true;
        while (capLeft > 0 && progress) {
          progress = false;
          for (const it of perPackage) {
            if (capLeft <= 0) break;
            const rem = remainingMap.get(it.size) || 0;
            if (rem > 0) {
              const idx = packItems.findIndex((x) => x.size === it.size);
              if (idx >= 0) packItems[idx].qty += 1;
              else packItems.push({ size: it.size, qty: 1 });
              remainingMap.set(it.size, rem - 1);
              capLeft -= 1;
              progress = true;
            }
          }
        }
      }

      const total = packItems.reduce((s, x) => s + x.qty, 0);
      partialPackages.push({ index: p + 1, items: packItems, total });
    }

    for (let i = 0; i < extraEmpty; i += 1) {
      partialPackages.push({ index: partialFromDemand + i + 1, items: [], total: 0 });
    }

    return {
      fullCount,
      notFullCount: partialPackages.length,
      packageTotal,
      partialPackages,
    };
  }, [pkgItems, colorOrderItems, copies]);

  useEffect(() => {
    setPkgItems(autoPackageItems);
  }, [autoPackageItems]);

  useEffect(() => {
    if (!copiesTouched) setCopies(suggestedCopies);
  }, [copiesTouched, suggestedCopies]);

  async function submitRec(e: React.FormEvent) {
    e.preventDefault();
    setRecMsg("");
    try {
      await api.post("/api/packaging/records", { work_order_id: id, ...rec });
      setRecMsg(t("msg.saved"));
    } catch (e: any) {
      setRecMsg(e.message);
    }
  }

  async function createPkg(e: React.FormEvent) {
    e.preventDefault();
    setPkgNotice(null);
    setIsCreating(true);
    try {
      const payload = {
        production_order_id: wo?.production_order_id,
        sales_order_id: po?.sales_order_id || null,
        model_id: po?.model_id,
        color,
        package_type: "bag",
        capacity,
        override_capacity: overrideCap,
        items: pkgItems.map((i) => ({ model_id: po?.model_id, color, size: i.size, quantity: i.quantity })),
      };
      if (copies > 1) {
        const r = await api.post("/api/packages/bulk", { ...payload, count: copies });
        setPkg({ id: r.package_ids?.[0], package_no: r.package_nos?.[0], barcode: "bulk" });
        const createdCount = Number(r?.count || copies || 0);
        const firstPackageNo = r?.package_nos?.[0];
        setPkgNotice({
          type: "success",
          text: firstPackageNo
            ? t("page.packaging.bulkCreatedWithFirst", { count: createdCount, no: firstPackageNo })
            : t("page.packaging.bulkCreated", { count: createdCount }),
        });
        if (r.package_ids?.length) {
          await api.openLabel(`/api/packages/label-sheet/by-ids?ids=${r.package_ids.join(",")}`);
        }
      } else {
        const r = await api.post("/api/packages", payload);
        setPkg(r);
        setPkgNotice({
          type: "success",
          text: t("page.packaging.singleCreated", { no: r?.package_no || "#" }),
        });
      }
    } catch (e: any) {
      setPkgNotice({ type: "error", text: e?.message || t("page.packaging.createFailed") });
    } finally {
      setIsCreating(false);
    }
  }

  function d(v?: string | null) {
    return v ? new Date(v).toLocaleDateString() : "-";
  }

  return (
    <div>
      <PageHeader title={t("page.packaging.title", { id })} subtitle={t("page.packaging.subtitle")} />
      <div className="card mb-4 p-4">
        <div className="grid grid-cols-1 gap-3 text-sm md:grid-cols-3">
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.shipments.salesOrder")}</div>
            <div className="font-medium">{so?.order_no || (po?.sales_order_id ? `#${po.sales_order_id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.customer")}</div>
            <div className="font-medium">{so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : "-"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.model")}</div>
            <div className="font-medium">{model ? `${model.code} - ${model.name}` : (po?.model_id ? `#${po.model_id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.productionOrder")}</div>
            <div className="font-medium">{po?.production_no || (po?.id ? `#${po.id}` : "-")}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.plannedQty")}</div>
            <div className="font-medium">{po?.planned_quantity ?? wo?.planned_output_qty ?? 0}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("common.status")}</div>
            <div className="font-medium">{wo?.status || "-"}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.salesDeadline")}</div>
            <div className="font-medium">{d(so?.deadline)}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.poDeadline")}</div>
            <div className="font-medium">{d(po?.deadline)}</div>
          </div>
          <div className="space-y-1">
            <div className="text-xs uppercase tracking-wide text-slate-500">{t("field.woDeadline")}</div>
            <div className="font-medium">{d(wo?.deadline)}</div>
          </div>
        </div>
        {Array.isArray(po?.items) && po.items.length > 0 && (
          <div className="mt-3 border-t border-[#ecebe3] pt-3">
            <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">{t("page.workOrder.breakdown")}</div>
            <div className="flex flex-wrap gap-2">
              {po.items.map((it: any) => (
                <span key={it.id} className="rounded-full bg-[#f5f2e8] px-3 py-1 text-xs text-[#5d5747]">
                  {(it.color || "-")} / {(it.size || "-")} / {it.planned_quantity ?? 0}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      <form onSubmit={submitRec} className="card mb-6 max-w-2xl space-y-3 p-6">
        <div>
          <label className="label">{t("field.inputQty")}</label>
          <input className="input" type="number" value={rec.input_qty} onChange={(e) => setRec({ ...rec, input_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.output")}</label>
          <input className="input" type="number" value={rec.packed_qty} onChange={(e) => setRec({ ...rec, packed_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.damaged")}</label>
          <input className="input" type="number" value={rec.damaged_qty} onChange={(e) => setRec({ ...rec, damaged_qty: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">{t("field.materialUsed")}</label>
          <input className="input" value={rec.packaging_material_used} onChange={(e) => setRec({ ...rec, packaging_material_used: e.target.value })} />
        </div>
        <button className="btn btn-primary">{t("btn.savePackagingRecord")}</button>
        {recMsg && <div className="text-sm text-slate-600">{recMsg}</div>}
      </form>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <form onSubmit={createPkg} className="card space-y-3 p-6">
          <h3 className="font-medium">{t("page.packaging.newPackage")}</h3>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="label">{t("field.color")}</label>
              <input className="input" value={color} onChange={(e) => setColor(e.target.value)} />
            </div>
            <div>
              <label className="label">{t("field.capacity")}</label>
              <input className="input" type="number" value={capacity} onChange={(e) => setCapacity(Number(e.target.value))} />
            </div>
            <label className="mb-2 flex items-end gap-2 text-sm">
              <input type="checkbox" checked={overrideCap} onChange={(e) => setOverrideCap(e.target.checked)} />
              {t("page.packaging.adminOverride")}
            </label>
            <div>
              <label className="label">{t("page.packaging.copies")}</label>
              <input
                className="input"
                min={1}
                type="number"
                value={copies}
                onChange={(e) => {
                  setCopiesTouched(true);
                  setCopies(Math.max(1, Number(e.target.value) || 1));
                }}
              />
            </div>
          </div>
          <div className="text-xs text-slate-500">
            {t("page.packaging.autoMixHint")}
          </div>

          <h4 className="text-sm font-medium">{t("page.packaging.sizesInPackage")}</h4>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.size")}</th>
                <th>{t("field.qty")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {pkgItems.map((it, i) => (
                <tr key={i}>
                  <td><input className="input" value={it.size} onChange={(e) => setPkgItems(pkgItems.map((x, j) => (j === i ? { ...x, size: e.target.value } : x)))} /></td>
                  <td><input className="input" type="number" value={it.quantity} onChange={(e) => setPkgItems(pkgItems.map((x, j) => (j === i ? { ...x, quantity: Number(e.target.value) } : x)))} /></td>
                  <td><button type="button" className="btn btn-danger" onClick={() => setPkgItems(pkgItems.filter((_, j) => j !== i))}>{t("btn.remove")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <button type="button" className="btn" onClick={() => setPkgItems([...pkgItems, { size: "L", quantity: 0 }])}>{t("btn.addSize")}</button>
          <div className="text-sm text-slate-500">{t("page.packaging.totalLine", { n: pkgItems.reduce((s, i) => s + Number(i.quantity || 0), 0) })}</div>

          <button className="btn btn-primary" disabled={isCreating}>
            {isCreating ? t("common.creating") : copies > 1 ? t("page.packaging.createCopies", { count: copies }) : t("btn.createPackage")}
          </button>
          {pkgNotice && (
            <div
              className={`rounded-md border px-3 py-2 text-sm ${
                pkgNotice.type === "success"
                  ? "border-green-300 bg-green-50 text-green-700"
                  : "border-red-300 bg-red-50 text-red-700"
              }`}
            >
              {pkgNotice.text}
            </div>
          )}
        </form>

        <div className="card p-6">
          <h3 className="font-medium">{t("page.packaging.partialTitle")}</h3>
          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.packaging.fullPackages")}</div>
              <div className="text-xl font-semibold">{packingPreview.fullCount}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.packaging.notFullPackages")}</div>
              <div className="text-xl font-semibold">{packingPreview.notFullCount}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.packaging.packCapacity")}</div>
              <div className="text-xl font-semibold">{packingPreview.packageTotal}</div>
            </div>
          </div>
          <div className="mt-4 text-xs text-slate-500">
            {t("page.packaging.previewHint")}
          </div>
          <div className="mt-3 space-y-2">
            {packingPreview.partialPackages.length === 0 ? (
              <div className="rounded-md border border-[#ecebe3] px-3 py-2 text-sm text-slate-500">{t("page.packaging.noPartial")}</div>
            ) : (
              packingPreview.partialPackages.map((p) => (
                <div key={p.index} className="rounded-md border border-[#ecebe3] px-3 py-2">
                  <div className="text-sm font-medium">
                    {t("page.packaging.packageN", { n: p.index })} - {p.total}/{packingPreview.packageTotal}
                  </div>
                  <div className="mt-1 text-xs text-slate-600">
                    {p.items.length
                      ? p.items.map((x) => `${x.size}: ${x.qty}`).join(" | ")
                      : t("page.packaging.emptyExtra")}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {pkg && (
        <div className="card mt-6 p-4">
          <h3 className="font-medium">{t("page.packaging.created", { no: pkg.package_no })}</h3>
          {pkg.barcode !== "bulk" && (
            <>
              <p className="text-sm text-slate-500">{t("field.barcode")}: <code>{pkg.barcode}</code></p>
              <button type="button" className="btn btn-primary mt-2" onClick={() => api.openLabel(`/api/packages/${pkg.id}/label`)}>{t("btn.printLabel")}</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
