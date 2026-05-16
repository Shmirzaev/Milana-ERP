"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
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

  const [rec, setRec] = useState({ input_qty: 0, packed_qty: 0, damaged_qty: 0, packaging_material_used: "", notes: "" });
  const [pkgItems, setPkgItems] = useState<{ size: string; quantity: number }[]>([{ size: "M", quantity: 30 }]);
  const [overrideCap, setOverrideCap] = useState(false);
  const [capacity, setCapacity] = useState(60);
  const [color, setColor] = useState("white");
  const [copies, setCopies] = useState(1);
  const [msg, setMsg] = useState("");
  const [pkg, setPkg] = useState<any>(null);

  async function submitRec(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
    try {
      await api.post("/api/packaging/records", { work_order_id: id, ...rec });
      setMsg(t("msg.saved"));
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  async function createPkg(e: React.FormEvent) {
    e.preventDefault();
    setMsg("");
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
        setMsg(`Created ${r.count} packages.`);
        if (r.package_ids?.length) {
          await api.openLabel(`/api/packages/label-sheet/by-ids?ids=${r.package_ids.join(",")}`);
        }
      } else {
        const r = await api.post("/api/packages", payload);
        setPkg(r);
      }
    } catch (e: any) {
      setMsg(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.packaging.title", { id })} subtitle={t("page.packaging.subtitle")} />
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
      </form>

      <form onSubmit={createPkg} className="card max-w-2xl space-y-3 p-6">
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
            <label className="label">Copies</label>
            <input className="input" min={1} type="number" value={copies} onChange={(e) => setCopies(Math.max(1, Number(e.target.value) || 1))} />
          </div>
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
        <button type="button" className="btn" onClick={() => setPkgItems([...pkgItems, { size: "L", quantity: 30 }])}>{t("btn.addSize")}</button>
        <div className="text-sm text-slate-500">{t("page.packaging.totalLine", { n: pkgItems.reduce((s, i) => s + Number(i.quantity || 0), 0) })}</div>

        <button className="btn btn-primary">{copies > 1 ? `Create ${copies} Copies` : t("btn.createPackage")}</button>
        {msg && <div className="text-sm text-red-600">{msg}</div>}
      </form>

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
