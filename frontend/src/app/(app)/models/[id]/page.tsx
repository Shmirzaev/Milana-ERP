"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useState } from "react";
import { useT } from "@/lib/i18n";

export default function ModelDetail() {
  const params = useParams<{ id: string }>();
  const { t } = useT();
  const id = params.id;
  const { data: m, mutate } = useSWR<any>(`/api/models/${id}`, fetcher);
  const { data: items } = useSWR<any[]>("/api/inventory/items", fetcher);
  const [bomRow, setBomRow] = useState({ item_id: 0, quantity_per_piece: 1, unit: "meter", waste_percent: 5 });
  const [color, setColor] = useState({ color_name: "", color_code: "" });
  const [size, setSize] = useState({ size: "" });
  if (!m) return <div>{t("common.loading")}</div>;

  async function addBom(e: React.FormEvent) {
    e.preventDefault();
    await api.post(`/api/models/${id}/bom`, bomRow);
    mutate();
  }
  async function addColor(e: React.FormEvent) {
    e.preventDefault();
    await api.post(`/api/models/${id}/colors`, color);
    setColor({ color_name: "", color_code: "" });
    mutate();
  }
  async function addSize(e: React.FormEvent) {
    e.preventDefault();
    await api.post(`/api/models/${id}/sizes`, size);
    setSize({ size: "" });
    mutate();
  }

  return (
    <div>
      <PageHeader title={`${m.code} — ${m.name}`} subtitle={`${t("field.status")}: ${t(`modelStatus.${m.status}`)}`} />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card p-4">
          <h3 className="font-medium mb-2">{t("page.modelDetail.sizes")}</h3>
          <ul className="text-sm mb-3">{m.sizes?.map((s: any) => <li key={s.id}>{s.size}</li>)}</ul>
          <form onSubmit={addSize} className="flex gap-2">
            <input className="input" placeholder="S, M, L…" value={size.size} onChange={(e) => setSize({ size: e.target.value })} />
            <button className="btn btn-primary">{t("btn.add")}</button>
          </form>
        </div>
        <div className="card p-4">
          <h3 className="font-medium mb-2">{t("page.modelDetail.colors")}</h3>
          <ul className="text-sm mb-3">{m.colors?.map((c: any) => <li key={c.id} className="flex items-center gap-2"><span className="inline-block w-3 h-3 rounded" style={{ background: c.color_code || "#ccc" }} />{c.color_name}</li>)}</ul>
          <form onSubmit={addColor} className="flex gap-2">
            <input className="input" placeholder={t("field.color")} value={color.color_name} onChange={(e) => setColor({ ...color, color_name: e.target.value })} />
            <input className="input w-20" placeholder="#hex" value={color.color_code} onChange={(e) => setColor({ ...color, color_code: e.target.value })} />
            <button className="btn btn-primary">{t("btn.add")}</button>
          </form>
        </div>
        <div className="card p-4 md:col-span-3">
          <h3 className="font-medium mb-2">{t("page.modelDetail.bom")}</h3>
          <table className="table mb-3">
            <thead><tr><th>{t("field.item")}</th><th>{t("page.modelDetail.qtyPerPiece")}</th><th>{t("field.unit")}</th><th>{t("page.modelDetail.wastePct")}</th></tr></thead>
            <tbody>{m.bom?.map((b: any) => <tr key={b.id}><td>{b.item_id}</td><td>{b.quantity_per_piece}</td><td>{b.unit}</td><td>{b.waste_percent}</td></tr>)}</tbody>
          </table>
          <form onSubmit={addBom} className="grid grid-cols-1 md:grid-cols-5 gap-2">
            <select className="input" value={bomRow.item_id} onChange={(e) => setBomRow({ ...bomRow, item_id: Number(e.target.value) })}>
              <option value={0}>—</option>
              {items?.map((i) => <option key={i.id} value={i.id}>{i.sku} — {i.name}</option>)}
            </select>
            <input className="input" type="number" step="0.001" placeholder={t("page.modelDetail.qtyPerPiece")} value={bomRow.quantity_per_piece} onChange={(e) => setBomRow({ ...bomRow, quantity_per_piece: Number(e.target.value) })} />
            <input className="input" placeholder={t("field.unit")} value={bomRow.unit} onChange={(e) => setBomRow({ ...bomRow, unit: e.target.value })} />
            <input className="input" type="number" step="0.1" placeholder={t("page.modelDetail.wastePct")} value={bomRow.waste_percent} onChange={(e) => setBomRow({ ...bomRow, waste_percent: Number(e.target.value) })} />
            <button className="btn btn-primary">{t("btn.addBomRow")}</button>
          </form>
        </div>
      </div>
    </div>
  );
}
