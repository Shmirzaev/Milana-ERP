"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Plus } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { VALID_SECTIONS, samePaidProcess, type SectionCode } from "@/lib/modelPaidOperations";
import { paidSectionLabel } from "@/lib/paidProcessSections";
import SearchableSelect from "@/components/SearchableSelect";

export type PaidProcessTemplate = { id: number; code: string; name: string; section: SectionCode };
const COPY = {
  en: { search: "Search paid processes by name or code", empty: "No matching process", add: "Add paid process", name: "Process name", create: "Save and select", cancel: "Cancel", section: "Section", failed: "Could not load or save the process. Please retry.", more: "Type more to narrow the results", duplicate: "This process is already in the list" },
  ru: { search: "Поиск платных операций по названию или коду", empty: "Операция не найдена", add: "Добавить платную операцию", name: "Название операции", create: "Сохранить и выбрать", cancel: "Отмена", section: "Раздел", failed: "Не удалось загрузить или сохранить операцию. Повторите попытку.", more: "Уточните запрос для поиска", duplicate: "Эта операция уже есть в списке" },
  uz: { search: "Haq to‘lanadigan jarayonni nomi yoki kodi bilan qidiring", empty: "Mos jarayon topilmadi", add: "Haq to‘lanadigan jarayon qo‘shish", name: "Jarayon nomi", create: "Saqlash va tanlash", cancel: "Bekor qilish", section: "Bo‘lim", failed: "Jarayonni yuklash yoki saqlash amalga oshmadi. Qayta urinib ko‘ring.", more: "Natijalarni aniqlashtirish uchun yozishni davom ettiring", duplicate: "Bu jarayon ro‘yxatda mavjud" },
};

export default function PaidProcessPicker({ onSelect, existing = [] }: { onSelect: (row: PaidProcessTemplate) => void; existing?: { name: string; section: string }[] }) {
  const { lang, t } = useT();
  const { me } = useMe();
  const canManage = can(me, "payroll.manage", "modeling.models");
  const copy = COPY[lang];
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [section, setSection] = useState<SectionCode>("sewing");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const [message, setMessage] = useState<"failed" | "duplicate" | null>(null);
  useEffect(() => { const timer = setTimeout(() => setSearch(query), 180); return () => clearTimeout(timer); }, [query]);
  const { data, error, isLoading, mutate } = useSWR<{ items: PaidProcessTemplate[]; has_more: boolean }>(canManage ? `/api/paid-processes?search=${encodeURIComponent(search)}` : null, fetcher);
  function choose(row: PaidProcessTemplate) {
    if (existing.some(item => samePaidProcess(item, row))) {
      setMessage("duplicate"); return;
    }
    setMessage(null); onSelect(row);
  }
  async function create() {
    if (busyRef.current || !name.trim()) return;
    busyRef.current = true; setBusy(true); setMessage(null);
    try {
      const row = await api.post<PaidProcessTemplate>("/api/paid-processes", { name: name.trim(), section });
      if (!mountedRef.current) return;
      choose(row); setCreating(false); setName(""); await mutate();
    } catch { if (mountedRef.current) setMessage("failed"); }
    finally { busyRef.current = false; if (mountedRef.current) setBusy(false); }
  }
  if (!canManage) return null;
  return <div className="space-y-2">
    <div className="flex flex-wrap items-center gap-2">
      <div className="min-w-[240px] flex-1">
        <SearchableSelect value={null} options={(data?.items || []).map(row => ({value: row.id, label: `${row.code} · ${row.name}`, metaText: paidSectionLabel(row.section, lang)}))}
          onChange={id => { const row = data?.items.find(item => item.id === id); if (row) choose(row); }}
          placeholder={copy.search} noResultsText={copy.empty} serverFilter onSearchChange={setQuery} loading={isLoading} loadingText={t("common.loading")} />
      </div>
      <button type="button" className="btn" onClick={() => { setCreating(!creating); setName(query); setMessage(null); }}><Plus className="h-4 w-4" />{copy.add}</button>
    </div>
    {data?.has_more && <p className="text-xs text-[#716a5c]">{copy.more}</p>}
    {(message || error) && <p role="alert" className="text-sm text-red-700">{copy[message || "failed"]}</p>}
    {creating && <div className="flex flex-wrap items-end gap-2 border border-[#ded9cc] p-3">
      <label className="min-w-[200px] flex-1"><span className="block text-sm">{copy.name}</span><input className="input" value={name} maxLength={255} onChange={event => setName(event.target.value)} /></label>
      <label><span className="block text-sm">{copy.section}</span><select className="input" value={section} onChange={event => setSection(event.target.value as SectionCode)}>{VALID_SECTIONS.map(value => <option key={value} value={value}>{paidSectionLabel(value, lang)}</option>)}</select></label>
      <button type="button" className="btn btn-primary" disabled={busy || !name.trim()} onClick={create}>{busy ? t("common.saving") : copy.create}</button>
      <button type="button" className="btn" disabled={busy} onClick={() => setCreating(false)}>{copy.cancel}</button>
    </div>}
  </div>;
}
