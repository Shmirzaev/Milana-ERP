"use client";
import { useMemo, useState } from "react";
import useSWR from "swr";
import { Plus, Search, Pencil, Trash2, BookOpen } from "lucide-react";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";

// ─── Types ───────────────────────────────────────────────────────────────────

type Passport = {
  id: number;
  passport_no: string;
  date: string;
  production_order_id: number | null;
  operator_id: number | null;
  variant: string | null;
  mold_no: string | null;
  fabric_type: string | null;
  has_print: boolean;
  lot_no: string | null;
  size_range: string | null;
  rolls_count: number | null;
  layer_weight_kg: number | null;
  total_layers: number | null;
  planned_kg: number | null;
  pieces: number | null;
  fabric_width_m: number | null;
  lay_length_m: number | null;
  gramage: number | null;
  waste_pct: number | null;
  beka_per_piece_kg: number | null;
  other_beka_per_piece_kg: number | null;
  scrap_kg: number | null;
  ribana_per_piece_kg: number | null;
  notes: string | null;
  // computed
  total_beka_kg: number | null;
  other_beka_kg: number | null;
  total_ribana_kg: number | null;
  actual_kg: number | null;
  pieces_per_layer: number | null;
  per_piece_weight_kg: number | null;
  theoretical_kg: number | null;
  actual_kg_per_piece: number | null;
  gross_kg_per_piece: number | null;
  // joined
  production_order_no: string | null;
  model_name: string | null;
  operator_name: string | null;
};

// ─── Example from Excel row 2 ─────────────────────────────────────────────────

const EXCEL_EXAMPLE = {
  passport_no: "6770",
  date: "2026-06-01",
  production_order_id: "" as string | number,
  operator_id: "" as string | number,
  variant: "4685",
  mold_no: "",
  fabric_type: "",
  has_print: false,
  lot_no: "D#11C#4",
  size_range: "44-52",
  rolls_count: 7 as string | number,
  layer_weight_kg: 2.4 as string | number,
  total_layers: 48 as string | number,
  planned_kg: 115 as string | number,
  pieces: 240 as string | number,
  fabric_width_m: 1.8 as string | number,
  lay_length_m: 3.37 as string | number,
  gramage: 0.191 as string | number,
  waste_pct: 15 as string | number,
  beka_per_piece_kg: 0.005 as string | number,
  other_beka_per_piece_kg: "" as string | number,
  scrap_kg: "" as string | number,
  ribana_per_piece_kg: "" as string | number,
  notes: "",
};

const EMPTY_FORM = {
  passport_no: "",
  date: new Date().toISOString().slice(0, 10),
  production_order_id: "" as string | number,
  operator_id: "" as string | number,
  variant: "",
  mold_no: "",
  fabric_type: "",
  has_print: false,
  lot_no: "",
  size_range: "",
  rolls_count: "" as string | number,
  layer_weight_kg: "" as string | number,
  total_layers: "" as string | number,
  planned_kg: "" as string | number,
  pieces: "" as string | number,
  fabric_width_m: "" as string | number,
  lay_length_m: "" as string | number,
  gramage: "" as string | number,
  waste_pct: "" as string | number,
  beka_per_piece_kg: "" as string | number,
  other_beka_per_piece_kg: "" as string | number,
  scrap_kg: "" as string | number,
  ribana_per_piece_kg: "" as string | number,
  notes: "",
};

// ─── Calculations (mirrors Excel formulas) ────────────────────────────────────

function compute(f: typeof EMPTY_FORM) {
  const R = Number(f.pieces) || 0;
  const Y = Number(f.beka_per_piece_kg) || 0;
  const AA = Number(f.other_beka_per_piece_kg) || 0;
  const AD = Number(f.ribana_per_piece_kg) || 0;
  const AB = Number(f.scrap_kg) || 0;
  const M = Number(f.layer_weight_kg) || 0;
  const N = Number(f.total_layers) || 0;
  const S = Number(f.fabric_width_m) || 0;
  const T = Number(f.lay_length_m) || 0;
  const V = Number(f.gramage) || 0;
  const O = Number(f.planned_kg) || 0;

  const X = R * Y;
  const Z = R * AA;
  const AC = R * AD;
  const P = M * N + AB + X;
  const piecesPerLayer = N ? R / N : 0;
  const AE = piecesPerLayer ? S * T * V / piecesPerLayer + Y + AA : 0;
  const Q = AE ? AE * R + X + AB : 0;
  const AF = R ? P / R : 0;
  const AG = R ? O / R : 0;

  return { X, Z, AC, P, Q, AE, AF, AG };
}

function d2(v: number | null | undefined) { return v ? v.toFixed(2) : "—"; }
function d3(v: number | null | undefined) { return v ? v.toFixed(3) : "—"; }
function d4(v: number | null | undefined) { return v ? v.toFixed(4) : "—"; }
function d6(v: number | null | undefined) { return v ? v.toFixed(6) : "—"; }

// ─── Page ────────────────────────────────────────────────────────────────────

export default function CuttingPassportsPage() {
  const { data: passports = [], mutate } = useSWR<Passport[]>("/api/cutting-passports", fetcher);
  const { data: prodOrders = [] } = useSWR<any[]>("/api/production-orders?page_size=500", fetcher);
  const { data: users = [] } = useSWR<any[]>("/api/admin/users", fetcher);

  const [q, setQ] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Passport | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [err, setErr] = useState("");

  const rows = useMemo(() => {
    if (!q.trim()) return passports;
    const lq = q.toLowerCase();
    return passports.filter((p) =>
      (p.passport_no || "").toLowerCase().includes(lq) ||
      (p.lot_no || "").toLowerCase().includes(lq) ||
      (p.model_name || "").toLowerCase().includes(lq) ||
      (p.production_order_no || "").toLowerCase().includes(lq) ||
      (p.variant || "").toLowerCase().includes(lq)
    );
  }, [passports, q]);

  const calc = compute(form);

  function openCreate() {
    setForm({ ...EMPTY_FORM, date: new Date().toISOString().slice(0, 10) });
    setEditing(null);
    setErr("");
    setShowForm(true);
  }

  function openEdit(p: Passport) {
    setForm({
      passport_no: p.passport_no,
      date: p.date.slice(0, 10),
      production_order_id: p.production_order_id ?? "",
      operator_id: p.operator_id ?? "",
      variant: p.variant ?? "",
      mold_no: p.mold_no ?? "",
      fabric_type: p.fabric_type ?? "",
      has_print: p.has_print,
      lot_no: p.lot_no ?? "",
      size_range: p.size_range ?? "",
      rolls_count: p.rolls_count ?? "",
      layer_weight_kg: p.layer_weight_kg ?? "",
      total_layers: p.total_layers ?? "",
      planned_kg: p.planned_kg ?? "",
      pieces: p.pieces ?? "",
      fabric_width_m: p.fabric_width_m ?? "",
      lay_length_m: p.lay_length_m ?? "",
      gramage: p.gramage ?? "",
      waste_pct: p.waste_pct ?? "",
      beka_per_piece_kg: p.beka_per_piece_kg ?? "",
      other_beka_per_piece_kg: p.other_beka_per_piece_kg ?? "",
      scrap_kg: p.scrap_kg ?? "",
      ribana_per_piece_kg: p.ribana_per_piece_kg ?? "",
      notes: p.notes ?? "",
    });
    setEditing(p);
    setErr("");
    setShowForm(true);
  }

  function num(v: string | number) {
    const n = Number(v);
    return isNaN(n) || v === "" ? null : n;
  }

  function buildPayload() {
    return {
      passport_no: form.passport_no,
      date: new Date(form.date).toISOString(),
      production_order_id: num(form.production_order_id),
      operator_id: num(form.operator_id),
      variant: form.variant || null,
      mold_no: form.mold_no || null,
      fabric_type: form.fabric_type || null,
      has_print: form.has_print,
      lot_no: form.lot_no || null,
      size_range: form.size_range || null,
      rolls_count: num(form.rolls_count),
      layer_weight_kg: num(form.layer_weight_kg),
      total_layers: num(form.total_layers),
      planned_kg: num(form.planned_kg),
      pieces: num(form.pieces),
      fabric_width_m: num(form.fabric_width_m),
      lay_length_m: num(form.lay_length_m),
      gramage: num(form.gramage),
      waste_pct: num(form.waste_pct),
      beka_per_piece_kg: num(form.beka_per_piece_kg),
      other_beka_per_piece_kg: num(form.other_beka_per_piece_kg),
      scrap_kg: num(form.scrap_kg),
      ribana_per_piece_kg: num(form.ribana_per_piece_kg),
      notes: form.notes || null,
    };
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    if (!form.passport_no) { setErr("Паспорт № талаб қилинади"); return; }
    try {
      if (editing) {
        await api.put(`/api/cutting-passports/${editing.id}`, buildPayload());
      } else {
        await api.post("/api/cutting-passports", buildPayload());
      }
      await mutate();
      setShowForm(false);
    } catch (e: any) {
      setErr(e.message || "Сақлашда хатолик");
    }
  }

  async function del(p: Passport) {
    if (!confirm(`Паспорт ${p.passport_no} ни ўчириш?`)) return;
    await api.delete(`/api/cutting-passports/${p.id}`);
    mutate();
  }

  const prodOrdersArr: any[] = Array.isArray(prodOrders) ? prodOrders : (prodOrders as any)?.rows ?? [];
  const usersArr: any[] = Array.isArray(users) ? users : [];
  const f = form;
  const sf = (k: keyof typeof EMPTY_FORM) => (e: React.ChangeEvent<any>) =>
    setForm((prev) => ({ ...prev, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  return (
    <div>
      <PageHeader
        title="Кроёк паспортлари"
        subtitle="Layup log with material consumption calculations"
      />

      {/* Toolbar */}
      <div className="mb-4 flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
          <input
            className="input pl-8"
            placeholder="Паспорт №, партия, модель…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <button className="btn btn-primary flex items-center gap-1.5" onClick={openCreate}>
          <Plus className="h-4 w-4" /> Янги паспорт
        </button>
      </div>

      {/* Table */}
      <div className="card overflow-x-auto">
        <table className="min-w-max text-xs">
          <thead>
            <tr className="border-b-2 border-slate-200 bg-slate-50 text-[11px] font-semibold text-slate-500 uppercase tracking-wide">
              <th className="px-3 py-2 text-left">Паспорт №</th>
              <th className="px-3 py-2 text-left">Дата</th>
              <th className="px-3 py-2 text-left">Модель</th>
              <th className="px-3 py-2 text-left">Вариант</th>
              <th className="px-3 py-2 text-left">Қолип №</th>
              <th className="px-3 py-2 text-left">Настилчи</th>
              <th className="px-3 py-2 text-left">МАТО</th>
              <th className="px-3 py-2 text-left">Печать</th>
              <th className="px-3 py-2 text-left">Заказ</th>
              <th className="px-3 py-2 text-left">Партия №</th>
              <th className="px-3 py-2 text-right">Рулон</th>
              <th className="px-3 py-2 text-right">Бир қақат</th>
              <th className="px-3 py-2 text-right">Жами қават</th>
              <th className="px-3 py-2 text-right">Берилган КГ</th>
              <th className="px-3 py-2 text-right bg-amber-50 text-amber-700">Реал КГ</th>
              <th className="px-3 py-2 text-right bg-amber-50 text-amber-700">Ишланган КГ</th>
              <th className="px-3 py-2 text-right">Иш сони</th>
              <th className="px-3 py-2 text-right">Мато эни</th>
              <th className="px-3 py-2 text-right">Настил м</th>
              <th className="px-3 py-2 text-left">Размер</th>
              <th className="px-3 py-2 text-right">Грамаж</th>
              <th className="px-3 py-2 text-right">Отход %</th>
              <th className="px-3 py-2 text-right bg-amber-50 text-amber-700">Бейка жами</th>
              <th className="px-3 py-2 text-right">Бейка/иш</th>
              <th className="px-3 py-2 text-right bg-amber-50 text-amber-700">Б.бейка жами</th>
              <th className="px-3 py-2 text-right">Б.бейка/иш</th>
              <th className="px-3 py-2 text-right">Брак кг</th>
              <th className="px-3 py-2 text-right bg-amber-50 text-amber-700">Рибана жами</th>
              <th className="px-3 py-2 text-right">Рибана/иш</th>
              <th className="px-3 py-2 text-right bg-green-50 text-green-700">Битта иш ГР</th>
              <th className="px-3 py-2 text-right bg-green-50 text-green-700">Слой ГР</th>
              <th className="px-3 py-2 text-right bg-green-50 text-green-700">БРУТТО ГР</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={33} className="py-10 text-center text-slate-400">
                  Паспортлар йўқ. «Янги паспорт» тугмасини босинг.
                </td>
              </tr>
            )}
            {rows.map((p) => (
              <tr key={p.id} className="border-b border-slate-100 hover:bg-stone-50">
                <td className="px-3 py-2 font-mono font-semibold">{p.passport_no}</td>
                <td className="px-3 py-2 whitespace-nowrap">{p.date.slice(0, 10)}</td>
                <td className="px-3 py-2">{p.model_name ?? "—"}</td>
                <td className="px-3 py-2">{p.variant ?? "—"}</td>
                <td className="px-3 py-2">{p.mold_no ?? "—"}</td>
                <td className="px-3 py-2">{p.operator_name ?? "—"}</td>
                <td className="px-3 py-2">{p.fabric_type ?? "—"}</td>
                <td className="px-3 py-2 text-center">{p.has_print ? "✓" : ""}</td>
                <td className="px-3 py-2 font-mono">{p.production_order_no ?? "—"}</td>
                <td className="px-3 py-2 font-mono">{p.lot_no ?? "—"}</td>
                <td className="px-3 py-2 text-right">{p.rolls_count ?? "—"}</td>
                <td className="px-3 py-2 text-right">{d3(p.layer_weight_kg)}</td>
                <td className="px-3 py-2 text-right">{p.total_layers ?? "—"}</td>
                <td className="px-3 py-2 text-right">{d2(p.planned_kg)}</td>
                <td className="px-3 py-2 text-right bg-amber-50 font-medium">{d3(p.actual_kg)}</td>
                <td className="px-3 py-2 text-right bg-amber-50 font-medium">{d3(p.theoretical_kg)}</td>
                <td className="px-3 py-2 text-right">{p.pieces ?? "—"}</td>
                <td className="px-3 py-2 text-right">{p.fabric_width_m ?? "—"}</td>
                <td className="px-3 py-2 text-right">{p.lay_length_m ?? "—"}</td>
                <td className="px-3 py-2">{p.size_range ?? "—"}</td>
                <td className="px-3 py-2 text-right">{p.gramage ?? "—"}</td>
                <td className="px-3 py-2 text-right">{p.waste_pct ?? "—"}</td>
                <td className="px-3 py-2 text-right bg-amber-50">{d4(p.total_beka_kg)}</td>
                <td className="px-3 py-2 text-right">{d6(p.beka_per_piece_kg)}</td>
                <td className="px-3 py-2 text-right bg-amber-50">{d4(p.other_beka_kg)}</td>
                <td className="px-3 py-2 text-right">{d6(p.other_beka_per_piece_kg)}</td>
                <td className="px-3 py-2 text-right">{d3(p.scrap_kg)}</td>
                <td className="px-3 py-2 text-right bg-amber-50">{d4(p.total_ribana_kg)}</td>
                <td className="px-3 py-2 text-right">{d6(p.ribana_per_piece_kg)}</td>
                <td className="px-3 py-2 text-right bg-green-50 font-semibold text-green-900">{d6(p.per_piece_weight_kg)}</td>
                <td className="px-3 py-2 text-right bg-green-50 font-semibold text-green-900">{d6(p.actual_kg_per_piece)}</td>
                <td className="px-3 py-2 text-right bg-green-50 font-semibold text-green-900">{d6(p.gross_kg_per_piece)}</td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    <button className="btn btn-ghost p-1" onClick={() => openEdit(p)}>
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    <button className="btn btn-ghost p-1 text-red-500" onClick={() => del(p)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Form modal */}
      <Modal
        open={showForm}
        onClose={() => setShowForm(false)}
        title={editing ? `Паспорт ${editing.passport_no} — таҳрир` : "Янги кроёк паспорти"}
        wide
      >
        <form onSubmit={save} className="max-h-[80vh] overflow-y-auto pr-1 space-y-5">

          {!editing && (
            <div className="flex items-center gap-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <BookOpen className="h-3.5 w-3.5 shrink-0" />
              <span>Мисол маълумот:</span>
              <button type="button" className="font-semibold underline" onClick={() => setForm({ ...EXCEL_EXAMPLE })}>
                Excel мисолини юклаш (паспорт 6770)
              </button>
            </div>
          )}

          {/* Асосий маълумот */}
          <Sec label="Асосий маълумот">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Паспорт № *">
                <input className="input" placeholder="мас. 6770" value={f.passport_no} onChange={sf("passport_no")} required />
              </Field>
              <Field label="Дата">
                <input className="input" type="date" value={f.date} onChange={sf("date")} />
              </Field>
            </div>
          </Sec>

          {/* Модель ва идентификация */}
          <Sec label="Модель ва идентификация">
            <div className="grid grid-cols-3 gap-3">
              <Field label="Заказ (Модель)">
                <select className="input" value={f.production_order_id} onChange={sf("production_order_id")}>
                  <option value="">— танланмаган —</option>
                  {prodOrdersArr.map((po: any) => (
                    <option key={po.id} value={po.id}>
                      {po.production_no}{po.model_name ? ` · ${po.model_name}` : ""}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Вариант">
                <input className="input" placeholder="мас. 4685" value={f.variant} onChange={sf("variant")} />
              </Field>
              <Field label="Қолип рақам">
                <input className="input" placeholder="Қолип №" value={f.mold_no} onChange={sf("mold_no")} />
              </Field>
            </div>
          </Sec>

          {/* Оператор ва лот */}
          <Sec label="Оператор ва лот">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Настилчи">
                <select className="input" value={f.operator_id} onChange={sf("operator_id")}>
                  <option value="">— танланмаган —</option>
                  {usersArr.map((u: any) => (
                    <option key={u.id} value={u.id}>{u.name}</option>
                  ))}
                </select>
              </Field>
              <Field label="Партия рақам">
                <input className="input" placeholder="мас. D#11C#4" value={f.lot_no} onChange={sf("lot_no")} />
              </Field>
              <Field label="МАТО">
                <input className="input" placeholder="Мато тури" value={f.fabric_type} onChange={sf("fabric_type")} />
              </Field>
              <Field label="Печать">
                <label className="flex h-9 items-center gap-2">
                  <input type="checkbox" className="h-4 w-4" checked={f.has_print} onChange={sf("has_print")} />
                  <span className="text-sm text-slate-600">Босма бор</span>
                </label>
              </Field>
            </div>
          </Sec>

          {/* Настил маълумотлари */}
          <Sec label="Настил маълумотлари">
            <div className="grid grid-cols-3 gap-3">
              <Field label="Рулон сони">
                <input className="input" type="number" placeholder="0" value={f.rolls_count} onChange={sf("rolls_count")} />
              </Field>
              <Field label="Бир қақат (кг)">
                <input className="input" type="number" step="0.001" placeholder="2.400" value={f.layer_weight_kg} onChange={sf("layer_weight_kg")} />
              </Field>
              <Field label="Жами қават">
                <input className="input" type="number" placeholder="48" value={f.total_layers} onChange={sf("total_layers")} />
              </Field>
              <Field label="Кройга берилган КГ">
                <input className="input" type="number" step="0.001" placeholder="115" value={f.planned_kg} onChange={sf("planned_kg")} />
              </Field>
              <Field label="Иш сони (деталлар)">
                <input className="input" type="number" placeholder="240" value={f.pieces} onChange={sf("pieces")} />
              </Field>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <CalcBox label="Реал холатда КГ" formula="= Бир қақат × Жами қават + Брак + Бейка жами">
                {calc.P ? calc.P.toFixed(3) : "—"}
              </CalcBox>
              <CalcBox label="Ишланган КГ" formula="= Битта иш ГР × Иш сони + Бейка жами + Брак">
                {calc.Q ? calc.Q.toFixed(3) : "—"}
              </CalcBox>
            </div>
          </Sec>

          {/* Мато ўлчовлари */}
          <Sec label="Мато ўлчовлари">
            <div className="grid grid-cols-3 gap-3">
              <Field label="Мато эни (м)">
                <input className="input" type="number" step="0.01" placeholder="1.80" value={f.fabric_width_m} onChange={sf("fabric_width_m")} />
              </Field>
              <Field label="Настил узунлиги (м)">
                <input className="input" type="number" step="0.01" placeholder="3.37" value={f.lay_length_m} onChange={sf("lay_length_m")} />
              </Field>
              <Field label="Размер">
                <input className="input" placeholder="44-52" value={f.size_range} onChange={sf("size_range")} />
              </Field>
              <Field label="Грамаж (кг/м²)">
                <input className="input" type="number" step="0.001" placeholder="0.191" value={f.gramage} onChange={sf("gramage")} />
              </Field>
              <Field label="Отход %">
                <input className="input" type="number" step="0.1" placeholder="15" value={f.waste_pct} onChange={sf("waste_pct")} />
              </Field>
            </div>
          </Sec>

          {/* Бейка ва рибана */}
          <Sec label="Бейка ва рибана (битта ишга)">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Битта ишга бейка (кг)">
                <input className="input" type="number" step="0.0001" placeholder="0.0050" value={f.beka_per_piece_kg} onChange={sf("beka_per_piece_kg")} />
              </Field>
              <Field label="Битта ишга бейка — бошка мато (кг)">
                <input className="input" type="number" step="0.0001" placeholder="0.0000" value={f.other_beka_per_piece_kg} onChange={sf("other_beka_per_piece_kg")} />
              </Field>
              <Field label="Брак бичиш учун (кг)">
                <input className="input" type="number" step="0.001" placeholder="0.000" value={f.scrap_kg} onChange={sf("scrap_kg")} />
              </Field>
              <Field label="Битта ишга рибана (кг)">
                <input className="input" type="number" step="0.0001" placeholder="0.0000" value={f.ribana_per_piece_kg} onChange={sf("ribana_per_piece_kg")} />
              </Field>
            </div>
            <div className="mt-3 grid grid-cols-3 gap-3">
              <CalcBox label="Бейка жами" formula="= Иш сони × Битта ишга бейка">
                {calc.X ? calc.X.toFixed(4) : "—"}
              </CalcBox>
              <CalcBox label="Бошка мато бейка жами" formula="= Иш сони × Бошка бейка">
                {calc.Z ? calc.Z.toFixed(4) : "—"}
              </CalcBox>
              <CalcBox label="Рибана жами" formula="= Иш сони × Битта ишга рибана">
                {calc.AC ? calc.AC.toFixed(4) : "—"}
              </CalcBox>
            </div>
          </Sec>

          {/* Натижалар */}
          <Sec label="Ҳисоблаш натижалари">
            <div className="grid grid-cols-3 gap-3">
              <CalcBox label="Битта иш ГР" formula="= Эни × Узунлик × Грамаж ÷ (Иш/Қават) + Бейка + Б.бейка" highlight>
                {calc.AE ? calc.AE.toFixed(6) : "—"}
              </CalcBox>
              <CalcBox label="Слой қават ГР" formula="= Реал КГ ÷ Иш сони" highlight>
                {calc.AF ? calc.AF.toFixed(6) : "—"}
              </CalcBox>
              <CalcBox label="БРУТТО ГР" formula="= Берилган КГ ÷ Иш сони" highlight>
                {calc.AG ? calc.AG.toFixed(6) : "—"}
              </CalcBox>
            </div>
          </Sec>

          {/* Изоҳ */}
          <Field label="Изоҳ">
            <textarea className="input" rows={2} placeholder="Қўшимча изоҳлар…" value={f.notes} onChange={sf("notes")} />
          </Field>

          {err && <p className="text-sm text-red-600">{err}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button type="button" className="btn" onClick={() => setShowForm(false)}>Бекор қилиш</button>
            <button type="submit" className="btn btn-primary">
              {editing ? "Сақлаш" : "Яратиш"}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function Sec({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400">{label}</p>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-slate-600">{label}</label>
      {children}
    </div>
  );
}

function CalcBox({ label, formula, children, highlight }: {
  label: string; formula: string; children: React.ReactNode; highlight?: boolean;
}) {
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${highlight ? "border-green-200 bg-green-50" : "border-amber-200 bg-amber-50"}`}>
      <p className={`mb-0.5 text-[10px] font-semibold ${highlight ? "text-green-700" : "text-amber-700"}`}>{label}</p>
      <p className={`text-lg font-bold ${highlight ? "text-green-900" : "text-amber-900"}`}>{children}</p>
      <p className="mt-0.5 text-[9px] text-slate-400">{formula}</p>
    </div>
  );
}
