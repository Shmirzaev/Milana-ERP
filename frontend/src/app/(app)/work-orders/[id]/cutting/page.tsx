"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type BundlePlan = { color: string; size: string; quantity: number; count: number; next: "sewing" | "printing" };

export default function CuttingPage() {
  const { t } = useT();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data: wo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: batches } = useSWR<any[]>("/api/inventory/batches", fetcher);

  const [form, setForm] = useState({
    fabric_batch_id: 0,
    input_quantity: 0,
    input_unit: "meter",
    cut_pieces: 0,
    passed_pieces: 0,
    defective_pieces: 0,
    waste_quantity: 0,
    waste_unit: "kg",
    notes: "",
  });
  const [bundles, setBundles] = useState<BundlePlan[]>([
    { color: "white", size: "M", quantity: 50, count: 1, next: "sewing" },
  ]);
  const [createdBundles, setCreatedBundles] = useState<any[]>([]);
  const [err, setErr] = useState("");

  function setB(i: number, p: Partial<BundlePlan>) {
    setBundles(bundles.map((b, j) => (i === j ? { ...b, ...p } : b)));
  }
  function addB() {
    setBundles([...bundles, { color: "white", size: "M", quantity: 50, count: 1, next: "sewing" }]);
  }
  function remB(i: number) {
    setBundles(bundles.filter((_, j) => j !== i));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try {
      const r = await api.post("/api/cutting/records", {
        work_order_id: id,
        ...form,
        fabric_batch_id: form.fabric_batch_id || null,
        bundles,
      });
      setCreatedBundles(r.bundles);
    } catch (e: any) {
      setErr(e.message);
    }
  }

  return (
    <div>
      <PageHeader
        title={t("page.cutting.title", { id })}
        subtitle={wo ? t("page.cutting.subtitle", { op: wo.operation, status: wo.status }) : ""}
      />
      <form onSubmit={submit} className="card space-y-5 p-6">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div>
            <label className="label">{t("field.fabricBatch")}</label>
            <select className="input" value={form.fabric_batch_id} onChange={(e) => setForm({ ...form, fabric_batch_id: Number(e.target.value) })}>
              <option value={0}>-</option>
              {batches?.map((b) => <option key={b.id} value={b.id}>{b.batch_no} ({b.color || ""} {b.quantity}{b.unit})</option>)}
            </select>
          </div>
          <div>
            <label className="label">{t("field.inputQty")}</label>
            <input className="input" type="number" step="0.01" value={form.input_quantity} onChange={(e) => setForm({ ...form, input_quantity: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.inputUnit")}</label>
            <input className="input" value={form.input_unit} onChange={(e) => setForm({ ...form, input_unit: e.target.value })} />
          </div>
          <div>
            <label className="label">{t("field.cutPieces")}</label>
            <input className="input" type="number" value={form.cut_pieces} onChange={(e) => setForm({ ...form, cut_pieces: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.passed")}</label>
            <input className="input" type="number" value={form.passed_pieces} onChange={(e) => setForm({ ...form, passed_pieces: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.defective")}</label>
            <input className="input" type="number" value={form.defective_pieces} onChange={(e) => setForm({ ...form, defective_pieces: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.wasteQty")}</label>
            <input className="input" type="number" step="0.01" value={form.waste_quantity} onChange={(e) => setForm({ ...form, waste_quantity: Number(e.target.value) })} />
          </div>
          <div>
            <label className="label">{t("field.wasteUnit")}</label>
            <input className="input" value={form.waste_unit} onChange={(e) => setForm({ ...form, waste_unit: e.target.value })} />
          </div>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="font-medium">{t("page.cutting.bundlePlan")}</h3>
            <button type="button" className="btn" onClick={addB}>{t("btn.addBundleLine")}</button>
          </div>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.color")}</th>
                <th>{t("field.size")}</th>
                <th>{t("field.bundleQty")}</th>
                <th>{t("field.count")}</th>
                <th>{t("field.next")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {bundles.map((b, i) => (
                <tr key={i}>
                  <td><input className="input" value={b.color} onChange={(e) => setB(i, { color: e.target.value })} /></td>
                  <td><input className="input" value={b.size} onChange={(e) => setB(i, { size: e.target.value })} /></td>
                  <td><input className="input" type="number" value={b.quantity} onChange={(e) => setB(i, { quantity: Number(e.target.value) })} /></td>
                  <td><input className="input" type="number" value={b.count} onChange={(e) => setB(i, { count: Number(e.target.value) })} /></td>
                  <td>
                    <select className="input" value={b.next} onChange={(e) => setB(i, { next: e.target.value as any })}>
                      <option value="sewing">{t("page.cutting.toSewing")}</option>
                      <option value="printing">{t("page.cutting.toPrinting")}</option>
                    </select>
                  </td>
                  <td><button type="button" className="btn btn-danger" onClick={() => remB(i)}>{t("btn.remove")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div>
          <label className="label">{t("common.notes")}</label>
          <textarea className="input" rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </div>

        {err && <div className="text-sm text-red-600">{err}</div>}
        <button className="btn btn-primary">{t("btn.saveCreateBundles")}</button>
      </form>

      {createdBundles.length > 0 && (
        <div className="card mt-6 p-4">
          <h3 className="mb-2 font-medium">{t("page.cutting.bundlesCreated")}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>{t("field.bundleNo")}</th>
                <th>{t("field.barcode")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {createdBundles.map((b) => (
                <tr key={b.id}>
                  <td>{b.bundle_no}</td>
                  <td><code>{b.barcode}</code></td>
                  <td><button type="button" className="text-brand-600 hover:underline" onClick={() => api.openLabel(`/api/bundles/${b.id}/label`)}>{t("common.print")}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
